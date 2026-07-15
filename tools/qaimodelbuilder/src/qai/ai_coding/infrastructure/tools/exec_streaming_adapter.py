# ---------------------------------------------------------------------
# Copyright (c) 2024-2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause
# ---------------------------------------------------------------------
"""Infrastructure adapter implementing :class:`ExecStreamingPort` (落点5).

Wraps ai_coding's own :func:`stream_tool_exec` engine and maps its
:class:`ExecStreamFrame` frames onto the application-layer
:class:`ExecStreamChunk` DTO so the route consumes a framework-free type.

``ExecStreamFrameKind`` → ``ExecStreamChunk.kind`` mapping:

* ``STARTED``     → ``"started"``
* ``STDOUT`` / ``STDERR`` → ``"output"`` (the route does not distinguish
  the two on the wire; V1 surfaced both as ``{type:"output"}``)
* ``CAP_REACHED`` → ``"cap_reached"``
* ``TERMINATED``  → ``"terminated"`` (carries exit_code / timed_out /
  truncated)

Layering: infrastructure → application (allowed); never imports
``interfaces.*`` / ``apps.*`` / ``qai.tools.*``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from qai.ai_coding.application.ports import ExecStreamChunk
from qai.ai_coding.infrastructure.tools.tool_exec_stream import (
    ExecStreamFrame,
    ExecStreamFrameKind,
    ExecStreamResult,
    stream_tool_exec,
)

__all__ = ["AiCodingExecStreamingAdapter"]


class AiCodingExecStreamingAdapter:
    """Concrete :class:`ExecStreamingPort` backed by :func:`stream_tool_exec`."""

    __slots__ = ("_guard_token_provider", "_ask_pending_probe", "_allow_x86")

    def __init__(
        self,
        *,
        guard_token_provider: Callable[[], str | None] | None = None,
        ask_pending_probe: Callable[[int], bool] | None = None,
        allow_x86: bool = False,
    ) -> None:
        # Zero-arg provider returning the live FileGuard guard-token (or
        # ``None``). Injected by the ``apps/api`` composition root (only layer
        # allowed to read the ``qai.security`` native-guard adapter). The
        # ``exec`` tool marks its spawned subtree as guarded (2026-07-06
        # guard-only reversal); re-read per spawn (State-Truth-First — the
        # guard starts lazily). ``None`` (default) injects no marker → child
        # bypassed (safe non-guarding default; keeps prior behaviour + tests).
        self._guard_token_provider = guard_token_provider
        # 2026-07-08 — probe(child_pid) → is a native ASK pending on it? Used
        # by stream_tool_exec's timeout to PAUSE instead of killing the child
        # while the user is deciding on a native FileGuard dialog. ``None`` →
        # timeout behaves as before (always fires). Injected by apps/api.
        self._ask_pending_probe = ask_pending_probe
        self._allow_x86 = allow_x86

    def _resolve_guard_token(self) -> str | None:
        provider = self._guard_token_provider
        if provider is None:
            return None
        try:
            token = provider()
        except Exception:  # noqa: BLE001 — never let token lookup break exec
            return None
        return token if isinstance(token, str) and token else None

    def stream(
        self,
        *,
        command: str,
        cwd: str | None = None,
        shell: str = "auto",
        timeout: float | None = None,
    ) -> "tuple[AsyncIterator[ExecStreamChunk], ExecStreamResult]":
        # ``stream_tool_exec`` is itself an ``async def`` returning the
        # ``(iterator, result)`` tuple; await it inside a thin async
        # generator so the port surface is synchronous-call → (iterator,
        # result), matching the use case's expectation.
        result = ExecStreamResult()
        guard_token = self._resolve_guard_token()

        async def _chunks() -> AsyncIterator[ExecStreamChunk]:
            inner_iter, inner_result = await stream_tool_exec(
                command,
                cwd=cwd,
                shell=shell,
                timeout=timeout,
                guard_token=guard_token,
                ask_pending_probe=self._ask_pending_probe,
                allow_x86=self._allow_x86,
            )
            async for frame in inner_iter:
                yield _to_chunk(frame)
            # Copy the populated accumulator fields onto the result the
            # caller already holds (the inner result is a fresh object).
            result.full_output = inner_result.full_output
            result.exit_code = inner_result.exit_code
            result.timed_out = inner_result.timed_out
            result.truncated = inner_result.truncated

        return _chunks(), result


def _to_chunk(frame: ExecStreamFrame) -> ExecStreamChunk:
    kind = frame.kind
    if kind is ExecStreamFrameKind.STARTED:
        return ExecStreamChunk(kind="started")
    if kind in (ExecStreamFrameKind.STDOUT, ExecStreamFrameKind.STDERR):
        return ExecStreamChunk(kind="output", data=frame.data)
    if kind is ExecStreamFrameKind.CAP_REACHED:
        return ExecStreamChunk(kind="cap_reached")
    # TERMINATED.
    meta: dict[str, Any] = frame.meta or {}
    exit_code = meta.get("exit_code")
    return ExecStreamChunk(
        kind="terminated",
        data=frame.data,
        exit_code=int(exit_code) if isinstance(exit_code, int) else None,
        timed_out=bool(meta.get("timed_out", False)),
        truncated=bool(meta.get("truncated", False)),
    )
