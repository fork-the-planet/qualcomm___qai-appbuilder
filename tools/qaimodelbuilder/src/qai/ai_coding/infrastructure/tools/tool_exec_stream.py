# ---------------------------------------------------------------------
# Copyright (c) 2024-2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
# ---------------------------------------------------------------------
"""Streaming shell-exec engine for the ai_coding context (落点5).

Real-time stdout/stderr tee for the universal ``POST /api/tool_execute_stream``
route.  This is ai_coding's OWN streaming engine — a sibling of the
non-streaming :func:`qai.ai_coding.infrastructure.tools.handlers.exec.tool_exec`
handler — so the ``context-isolation`` import-linter contract holds: the
route reaches it through an ``application`` port (``ExecStreamingPort``) and
the concrete adapter lives here in ``infrastructure``, never importing
``qai.tools.*`` (which the WIRE-tools lane parked its own
``tool_exec_stream`` under for the chat agentic loop).

Design mirrors the V1 ``backend/tools/_exec.py::_tool_exec_stream``:

* an **async generator** yielding :class:`ExecStreamFrame` dataclasses
  (``started`` → ``stdout`` / ``stderr`` / ``cap_reached`` → ``terminated``);
* spawns ``asyncio.create_subprocess_exec`` with separate stdout/stderr
  PIPEs, drained by two concurrent reader tasks feeding a shared queue;
* enforces an overall wall-clock ``timeout`` (kills the child on expiry);
* emits a single ``cap_reached`` frame once ``cap_bytes`` of output has
  streamed (output keeps flowing — informational only, V1 parity);
* accumulates the full output so the route can render a final ``done``
  envelope after the stream drains.

Layering (§3.5 import-linter):
  infrastructure may import domain / application / asyncio / stdlib;
  must NOT import ``backend.*`` / ``features.*`` / ``apps.*`` /
  ``interfaces.*`` / ``qai.tools.*`` / any other ``qai.<ctx>``.
"""

from __future__ import annotations

import asyncio
import enum
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from qai.ai_coding.infrastructure.tools.handlers._multiline_rewrite import (
    cleanup_temp_scripts,
    rewrite_multiline_to_argv,
)
from qai.ai_coding.infrastructure.tools.handlers._shared import default_cwd
from qai.ai_coding.infrastructure.tools.handlers.exec import (
    _build_exec_env,
    _ensure_cwd_exists,
    _resolve_shell,
    _select_shell,
)
from qai.platform.logging import get_logger
from qai.platform.process import (
    best_effort_tree_kill,
    no_window_creationflags,
    terminate_process_tree,
)

__all__ = [
    "EXEC_STREAM_CAP_BYTES",
    "ExecStreamFrame",
    "ExecStreamFrameKind",
    "ExecStreamResult",
    "stream_tool_exec",
]

_log = get_logger(__name__)


#: Bytes streamed before a single ``cap_reached`` frame is emitted.
#: Matches V1 ``EXEC_STREAM_CAP_BYTES`` (50 KB).
EXEC_STREAM_CAP_BYTES: int = 50 * 1024

# --- Output frame coalescing (throughput) ---
# Emitting ONE frame per stdout line makes a command that prints tens of
# thousands of lines crawl (every line pays the full per-frame cost through the
# SSE stack). Consecutive same-stream lines are coalesced into one frame, flushed
# on a byte (``_COALESCE_FLUSH_BYTES``) / time (``_COALESCE_FLUSH_SECONDS``)
# boundary, and always on a stream switch / EOF / timeout / cap. The frame shape
# is unchanged (``data`` carries several lines); full_output, the byte cap, and
# the SSE frame format are all unaffected.
_COALESCE_FLUSH_BYTES = 16 * 1024
_COALESCE_FLUSH_SECONDS = 0.1
# Bounded reader→drain queue: readers block on a full queue (back-pressure)
# rather than growing an unbounded backlog when the consumer is slower than the
# child's output rate.
_READER_QUEUE_MAXSIZE = 10000


class ExecStreamFrameKind(enum.Enum):
    """Discriminator for frames yielded by :func:`stream_tool_exec`."""

    STARTED = "started"
    STDOUT = "stdout"
    STDERR = "stderr"
    CAP_REACHED = "cap_reached"
    TERMINATED = "terminated"


@dataclass(frozen=True, slots=True)
class ExecStreamFrame:
    """One frame of streaming exec output.

    Attributes:
        kind: Frame discriminator.
        data: Text payload (stdout/stderr line, or diagnostic message).
        meta: Optional dict with extra info (pid, exit_code, timed_out, ...).
    """

    kind: ExecStreamFrameKind
    data: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecStreamResult:
    """Accumulator populated during iteration of :func:`stream_tool_exec`.

    After the iterator drains, ``full_output`` holds the complete
    stdout+stderr text and ``exit_code`` the child's return code.
    """

    full_output: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False


def _select_shell_argv(command: str, shell: str) -> list[str]:
    """Return the argv list for the chosen interpreter.

    S1: delegates to the non-streaming handler's
    :func:`qai.ai_coding.infrastructure.tools.handlers.exec._select_shell` so
    the streaming and one-shot exec paths share a SINGLE source of truth for
    shell selection.  This restores V1 parity (``_exec.py:255-409``) that the
    old local 3-heuristic copy had dropped: the full 6-rule
    ``_detect_shell_type`` (cmdlet verb set / PS operators / ``|%`` / ``|?`` /
    Out-File / ``$``-vars), the PowerShell alias-removal prelude
    (``ls``/``cat``/... → real Unix .exe on PATH) and the
    ``-ExecutionPolicy Bypass`` flag (restricted-policy machines).  Same module
    / same context — no cross-context import (§3.2).
    """
    argv, _ = _select_shell(command, shell)
    return argv


def _probe_ask_pending(
    probe: "Callable[[int], bool]", pid: int
) -> bool:
    """Safely call the native-ASK-pending probe; any error → ``False``.

    Never raises — a probe glitch must never STALL a timeout kill (orphan
    safety); on uncertainty we let the deadline fire.
    """
    try:
        return bool(probe(pid))
    except Exception:  # noqa: BLE001 — probe failure must not stall the kill
        return False


async def stream_tool_exec(
    command: str,
    *,
    cwd: str | None = None,
    shell: str = "auto",
    timeout: float | None = None,
    cap_bytes: int = EXEC_STREAM_CAP_BYTES,
    guard_token: str | None = None,
    ask_pending_probe: "Callable[[int], bool] | None" = None,
    allow_x86: bool = False,
) -> tuple[AsyncIterator[ExecStreamFrame], ExecStreamResult]:
    """Spawn *command* and stream its output in real time.

    Returns ``(frame_iterator, result_accumulator)``: iterate the first to
    drive I/O; read the second after the iterator drains for the aggregated
    text + exit status.

    Args:
        command: Shell command string.
        cwd: Working directory for the child process.
        shell: ``"auto"`` | ``"cmd"`` | ``"powershell"`` | ``"sh"``.
        timeout: Max seconds before the child is killed. ``None`` / ``0`` (the
            default) means NO timeout — the command runs to completion (V1/v0.5
            parity: omitting the timeout never killed long builds/installs).
            Only a positive value arms the deadline.
        cap_bytes: Emit one ``cap_reached`` frame after this many bytes.
        guard_token: Optional FileGuard guard-token. When non-empty it is
            injected as ``QAI_FILEGUARD_GUARD_TOKEN`` into the child env so
            the native ``guard64.dll`` guards this exec subtree (2026-07-06
            guard-only reversal). ``None`` (guard off / not started) leaves
            the child inheriting the host env unmarked → bypassed.
    """
    result = ExecStreamResult()
    # V1/v0.5 parity (AGENTS.md 🟢): omit/0 = NO timeout (the prior V2 default
    # of 120s silently killed long but legitimate commands). ``_stream_impl``
    # arms the deadline only when ``timeout > 0``, so ``0.0`` == unbounded.
    effective_timeout = (
        timeout if (timeout is not None and timeout > 0) else 0.0
    )
    return (
        _stream_impl(
            command,
            cwd=cwd,
            shell=shell,
            timeout=effective_timeout,
            cap_bytes=cap_bytes,
            result=result,
            guard_token=guard_token,
            ask_pending_probe=ask_pending_probe,
            allow_x86=allow_x86,
        ),
        result,
    )


async def _stream_impl(
    command: str,
    *,
    cwd: str | None,
    shell: str,
    timeout: float,
    cap_bytes: int,
    result: ExecStreamResult,
    guard_token: str | None = None,
    ask_pending_probe: "Callable[[int], bool] | None" = None,
    allow_x86: bool = False,
) -> AsyncIterator[ExecStreamFrame]:
    """Core async generator implementing the streaming tee logic."""
    # Multi-line command support on the tokenised-argv exec path. A multi-line
    # cmd body cannot be carried as a single ``["cmd","/c",command]`` element
    # (``list2cmdline`` + cmd.exe double-parse drops trailing lines / mangles
    # quotes). ZERO-PARSE fix: materialise the whole command verbatim into a
    # ``.bat`` and run ``["cmd","/c","<tmp>.bat"]`` — cmd.exe applies its own
    # per-line parsing; the command CONTENT is never parsed. The ORIGINAL
    # ``command`` is preserved for the STARTED frame / diagnostics; temp files
    # are unlinked in the ``finally``. ``(None, [])`` for single-line /
    # powershell / sh → fall back to ``_select_shell``.
    resolved_shell = _resolve_shell(command, (shell or "auto").lower())
    rewritten_argv, tmp_paths = rewrite_multiline_to_argv(
        command, resolved_shell
    )
    try:
        if rewritten_argv is not None:
            argv = rewritten_argv
        else:
            argv = _select_shell_argv(command, resolved_shell)
    except Exception:
        # ``_select_shell`` may raise a ToolError (e.g. sh/bash unavailable)
        # AFTER the rewrite already materialised temp script(s) — unlink them
        # here so they do not leak, then re-raise (the main try/finally below
        # is only entered once ``argv`` is bound). ``_select_shell_argv`` is a
        # pure sync call, so ToolError (an ``Exception``) is the only failure.
        cleanup_temp_scripts(tmp_paths)
        raise

    # Mirror the non-streaming exec.py path (tool_exec:379-390): resolve a
    # missing cwd to the workspace base, then materialise it so the OS never
    # rejects the spawn with [Errno 2] No such file or directory.
    if not cwd:
        cwd = default_cwd()
    if cwd:
        cwd = _ensure_cwd_exists(cwd)

    # Build the child env via _build_exec_env so PATH always includes the
    # venv bin/ directory — mirroring the non-streaming exec.py path exactly.
    # Previously this block only set child_env when guard_token was truthy,
    # leaving child_env=None (bare os.environ) otherwise; on machines where
    # the parent process PATH does not contain /bin or /usr/bin (e.g. inside
    # a venv-activated shell on Ubuntu), sh was not found and
    # asyncio.create_subprocess_exec raised [Errno 2] No such file or directory
    # before the command even ran.
    child_env = _build_exec_env(guard_token=guard_token, allow_x86=allow_x86)

    # TEMP DIAGNOSTIC (2026-07-12): streaming path spawn — capture argv, cwd,
    # creationflags, PATH so a 0xC000007B spawn crash can be diagnosed.
    try:
        import os as _os
        from pathlib import Path as _P
        _cf = no_window_creationflags()
        with open(
            _P(_os.environ.get("TEMP", "C:/Windows/Temp")) / "qai_sh_debug.log",
            "a", encoding="utf-8",
        ) as _fh:
            import datetime as _dt
            _fh.write(
                f"[{_dt.datetime.now().isoformat()}] pid={_os.getpid()} "
                f"STREAM_SPAWN argv={list(argv)} cwd={cwd!r} "
                f"creationflags=0x{_cf:X} "
                f"PATH_head={child_env.get('PATH','')[:400]!r}\n"
            )
    except Exception:
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=child_env,
            # Windows: don't flash a console window for the child (no-op on
            # POSIX). stdout/stderr are still captured via the pipes above.
            creationflags=no_window_creationflags(),
        )
    except (FileNotFoundError, OSError) as exc:
        # Surface a single terminated frame with the spawn error rather
        # than raising — the route turns it into an SSE error envelope.
        msg = f"[exec: subprocess spawn failed: {exc}]"
        result.full_output = msg
        result.exit_code = -1
        # Spawn failed before the main try/finally was entered — unlink the
        # materialised multi-line temp script(s) here so they do not leak on
        # this early-return path (the finally below is never reached).
        cleanup_temp_scripts(tmp_paths)
        yield ExecStreamFrame(
            kind=ExecStreamFrameKind.TERMINATED,
            data=msg,
            meta={"exit_code": -1, "timed_out": False, "truncated": False,
                  "total_bytes": 0, "spawn_failed": True},
        )
        return

    pid = proc.pid or 0
    # Reader tasks declared here so the finally can always tear them down, even
    # if the consumer stops right after the STARTED frame (before they spawn).
    stdout_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None
    watchdog_task: asyncio.Task[None] | None = None
    # Aggregates referenced after the loop; initialised here so they are always
    # bound even if the consumer aborts iteration before the loop ran.
    collected: list[str] = []
    total_bytes = 0
    cap_noticed = False
    timed_out = False
    watchdog_fired = False
    try:
        yield ExecStreamFrame(
            kind=ExecStreamFrameKind.STARTED,
            meta={"pid": pid, "command": command},
        )

        queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue(
            maxsize=_READER_QUEUE_MAXSIZE
        )

        async def _read_stream(
            stream: asyncio.StreamReader | None, tag: str
        ) -> None:
            if stream is None:
                await queue.put((f"eof_{tag}", None))
                return
            try:
                while True:
                    line_bytes = await stream.readline()
                    if not line_bytes:
                        break
                    await queue.put(
                        (tag, line_bytes.decode("utf-8", errors="replace"))
                    )
            except Exception as exc:  # noqa: BLE001 — best-effort reader.
                _log.debug(
                    "ai_coding.exec_stream.reader_error", tag=tag,
                    error=str(exc),
                )
            finally:
                await queue.put((f"eof_{tag}", None))

        stdout_task = asyncio.create_task(_read_stream(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(_read_stream(proc.stderr, "stderr"))

        # --- Wall-clock timeout watchdog ---
        # The in-loop deadline check only runs when the loop reaches its top,
        # which requires each ``yield`` to return — i.e. it depends on the
        # downstream consumer pulling. A command that floods output (or a
        # slow/stalled consumer) can park the generator at a ``yield``
        # indefinitely, starving the in-loop check so the timeout never fires.
        # This INDEPENDENT watchdog force-kills the process tree on the deadline
        # regardless of where the loop is parked; the child's pipes then hit EOF
        # and the loop drains + ends. ``watchdog_fired`` tells the post-loop code
        # to report the timeout.
        async def _timeout_watchdog(budget: float) -> None:
            nonlocal watchdog_fired
            try:
                await asyncio.sleep(budget)
            except asyncio.CancelledError:
                return
            # 2026-07-08 — pause the timeout while the child is BLOCKED on a
            # native FileGuard authorization dialog (State-Truth-First: probe
            # the pending-permission authority via the injected callable). If a
            # native ASK is pending on this child tree, re-sleep another budget
            # instead of killing, so the user's decision time is not counted
            # against the timeout. Orphan-safe: without a pending ASK (or no
            # probe / probe error) the child is still force-killed on time.
            while (
                ask_pending_probe is not None
                and proc.pid is not None
                and _probe_ask_pending(ask_pending_probe, proc.pid)
            ):
                try:
                    await asyncio.sleep(budget)
                except asyncio.CancelledError:
                    return
            watchdog_fired = True
            best_effort_tree_kill(proc)

        if timeout > 0:
            watchdog_task = asyncio.create_task(_timeout_watchdog(timeout))

        collected = []
        total_bytes = 0
        cap_noticed = False
        timed_out = False
        eof_count = 0

        # Coalescing buffer: accumulate consecutive same-stream text and flush
        # it as ONE frame on a byte / time boundary (see the constants above).
        pending_tag: str | None = None
        pending_buf: list[str] = []
        pending_bytes = 0
        last_flush = asyncio.get_event_loop().time()

        deadline = (
            asyncio.get_event_loop().time() + timeout if timeout > 0 else None
        )

        while eof_count < 2:
            if deadline is not None:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    # 2026-07-08 — pause the timeout while the child is BLOCKED
                    # on a native FileGuard authorization dialog: if a native
                    # ASK is pending on this child tree, push the deadline out
                    # another ``timeout`` slice instead of killing, so the
                    # user's decision time is not counted against the timeout.
                    # Orphan-safe: without a pending ASK the kill below fires.
                    if (
                        ask_pending_probe is not None
                        and proc.pid is not None
                        and _probe_ask_pending(ask_pending_probe, proc.pid)
                    ):
                        deadline = asyncio.get_event_loop().time() + timeout
                        wait_timeout = _COALESCE_FLUSH_SECONDS
                    else:
                        # Flush buffered output before the timeout marker so
                        # frame ordering stays faithful to the byte stream.
                        if pending_buf:
                            kind = (
                                ExecStreamFrameKind.STDOUT
                                if pending_tag == "stdout"
                                else ExecStreamFrameKind.STDERR
                            )
                            yield ExecStreamFrame(
                                kind=kind, data="".join(pending_buf)
                            )
                            pending_buf = []
                            pending_bytes = 0
                            pending_tag = None
                        # Tree kill so a grandchild the command spawned is
                        # stopped too, not just the direct shell child.
                        best_effort_tree_kill(proc)
                        timed_out = True
                        msg = (
                            f"\n[process killed: timeout after {timeout:.0f}s]\n"
                        )
                        collected.append(msg)
                        yield ExecStreamFrame(
                            kind=ExecStreamFrameKind.STDERR, data=msg
                        )
                        break
                else:
                    wait_timeout = min(remaining, _COALESCE_FLUSH_SECONDS)
            else:
                wait_timeout = _COALESCE_FLUSH_SECONDS

            try:
                tag, text = await asyncio.wait_for(
                    queue.get(), timeout=wait_timeout
                )
            except asyncio.TimeoutError:
                # Flush buffered output so a slow trickle still surfaces.
                if pending_buf:
                    kind = (
                        ExecStreamFrameKind.STDOUT
                        if pending_tag == "stdout"
                        else ExecStreamFrameKind.STDERR
                    )
                    yield ExecStreamFrame(kind=kind, data="".join(pending_buf))
                    pending_buf = []
                    pending_bytes = 0
                    pending_tag = None
                    last_flush = asyncio.get_event_loop().time()
                continue

            if tag.startswith("eof_"):
                eof_count += 1
                continue

            assert text is not None
            line_len = len(text.encode("utf-8"))
            collected.append(text)
            total_bytes += line_len

            if total_bytes > cap_bytes and not cap_noticed:
                cap_noticed = True
                if pending_buf:
                    kind = (
                        ExecStreamFrameKind.STDOUT
                        if pending_tag == "stdout"
                        else ExecStreamFrameKind.STDERR
                    )
                    yield ExecStreamFrame(kind=kind, data="".join(pending_buf))
                    pending_buf = []
                    pending_bytes = 0
                    pending_tag = None
                yield ExecStreamFrame(
                    kind=ExecStreamFrameKind.CAP_REACHED,
                    meta={"bytes": total_bytes},
                )

            # Flush first if this line switches stream, so stdout/stderr never
            # interleave within one frame, then append.
            if pending_tag is not None and tag != pending_tag and pending_buf:
                kind = (
                    ExecStreamFrameKind.STDOUT
                    if pending_tag == "stdout"
                    else ExecStreamFrameKind.STDERR
                )
                yield ExecStreamFrame(kind=kind, data="".join(pending_buf))
                pending_buf = []
                pending_bytes = 0
            pending_tag = tag
            pending_buf.append(text)
            pending_bytes += line_len

            now = asyncio.get_event_loop().time()
            if (
                pending_bytes >= _COALESCE_FLUSH_BYTES
                or now - last_flush >= _COALESCE_FLUSH_SECONDS
            ):
                kind = (
                    ExecStreamFrameKind.STDOUT
                    if pending_tag == "stdout"
                    else ExecStreamFrameKind.STDERR
                )
                yield ExecStreamFrame(kind=kind, data="".join(pending_buf))
                pending_buf = []
                pending_bytes = 0
                pending_tag = None
                last_flush = now

        # Flush any residual buffered output after the loop (normal EOF path).
        if pending_buf:
            kind = (
                ExecStreamFrameKind.STDOUT
                if pending_tag == "stdout"
                else ExecStreamFrameKind.STDERR
            )
            yield ExecStreamFrame(kind=kind, data="".join(pending_buf))

        # The watchdog force-killed the child on the wall-clock deadline (the
        # loop then ended via EOF rather than the in-loop deadline branch).
        if watchdog_fired and not timed_out:
            timed_out = True
            msg = f"\n[process killed: timeout after {timeout:.0f}s]\n"
            collected.append(msg)
            yield ExecStreamFrame(kind=ExecStreamFrameKind.STDERR, data=msg)
    finally:
        # Runs on normal completion, timeout break, AND when the consumer stops
        # iterating (user "Stop" → the async generator is closed, raising
        # GeneratorExit / CancelledError here): the child + any subtree it
        # spawned must not be left running, and the reader tasks must be torn
        # down so they do not leak.
        #
        # During ``aclose()`` the loop only drives the finally for a single
        # await step, so the SYNCHRONOUS tree kill must fire FIRST (it signals
        # the child + subtree without awaiting); the awaited reap below is a
        # best-effort zombie collection.
        if proc.returncode is None:
            best_effort_tree_kill(proc)
        for task in (stdout_task, stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 — best-effort cleanup.
                    _log.warning("ai_coding.exec_stream.reader_cleanup_failed")
        # Cancel the wall-clock watchdog (no-op if it already fired / never armed).
        if watchdog_task is not None and not watchdog_task.done():
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 — best-effort cleanup.
                _log.warning("ai_coding.exec_stream.watchdog_cleanup_failed")
        # Best-effort reap; shielded so a re-cancel cannot interrupt it. Swallow
        # the cancel HERE so we never mask the GeneratorExit aclose() delivers.
        try:
            await asyncio.shield(terminate_process_tree(proc))
        except asyncio.CancelledError:
            pass
        # Unlink the materialised multi-line temp script(s) (best-effort, no-op
        # when empty) on EVERY exit path (normal drain / timeout / consumer
        # aclose) so a rewritten multi-line body never leaks a temp file.
        cleanup_temp_scripts(tmp_paths)

    exit_code = proc.returncode if proc.returncode is not None else -1

    result.full_output = "".join(collected)
    result.exit_code = exit_code
    result.timed_out = timed_out
    result.truncated = cap_noticed

    yield ExecStreamFrame(
        kind=ExecStreamFrameKind.TERMINATED,
        meta={
            "exit_code": exit_code,
            "timed_out": timed_out,
            "truncated": cap_noticed,
            "total_bytes": total_bytes,
        },
    )
