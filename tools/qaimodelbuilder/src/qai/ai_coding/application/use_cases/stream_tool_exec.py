"""Use case: stream a shell command's output in real time (落点5).

Backs the real-time path of the universal ``POST /api/tool_execute_stream``
route for the ``exec`` tool.  V1 surfaced live stdout/stderr as
``{type:"output"}`` SSE frames (``backend/tools/_exec.py:1010``) between the
``start`` and ``done`` envelopes; the WIRE-tools lane already restored this
on the **chat** agentic loop, but the universal one-button route was left
emitting only the one-shot ``done`` envelope because streaming it inline
would force ``interfaces.http`` to import the infrastructure exec engine
(which the ``interfaces-stays-thin`` / ``context-isolation`` contracts
forbid).

落点5 closes that gap **inside the ai_coding lane**: this application use
case fronts an :class:`ExecStreamingPort`, whose concrete adapter wraps
ai_coding's OWN ``stream_tool_exec`` infrastructure engine (a sibling of
the non-streaming ``exec`` handler — NOT ``qai.tools.*``).  The route
depends only on this use case + port, so the import-linter contracts hold.

Behaviour:

* For the ``exec`` tool the use case streams ``output`` / ``cap_reached``
  chunks and returns an accumulator the route reads for the final
  ``done`` envelope.
* ``applies_to`` lets the route decide per-request whether to take the
  streaming path (``exec``) or fall back to the existing one-shot
  :class:`ExecuteToolDirectlyUseCase` ``done`` envelope (every other
  tool — they have no incremental output to stream).

Cross-context isolation: imports only ``qai.ai_coding.{application}`` +
stdlib.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from qai.ai_coding.application.ports import (
    ExecStreamChunk,
    ExecStreamingPort,
)

__all__ = [
    "StreamToolExecUseCase",
]


#: The single tool whose output streams incrementally.  Every other tool
#: returns a structured result in one shot (no live stdout to tee), so the
#: route keeps the existing ``done``-only envelope for them.
_STREAMABLE_TOOL = "exec"


class StreamToolExecUseCase:
    """Stream the ``exec`` tool's stdout/stderr via :class:`ExecStreamingPort`."""

    def __init__(self, *, exec_streaming_port: ExecStreamingPort) -> None:
        self._exec_streaming_port = exec_streaming_port

    @staticmethod
    def applies_to(tool_name: str) -> bool:
        """Return ``True`` when ``tool_name`` supports real-time streaming.

        Only ``exec`` streams incrementally; the route uses this to decide
        between the streaming path and the one-shot ``done`` envelope.
        """
        return tool_name == _STREAMABLE_TOOL

    def stream(
        self,
        *,
        args: dict[str, Any],
    ) -> "tuple[AsyncIterator[ExecStreamChunk], Any]":
        """Begin streaming ``exec`` output for ``args``.

        ``args`` mirrors the ``exec`` tool's argument shape
        (``command`` / ``cwd`` / ``shell`` / ``timeout``).  Returns the
        ``(chunk_iterator, accumulator)`` pair from the port unchanged so
        the route can iterate chunks and then read the accumulator's
        ``full_output`` / ``exit_code`` for the final envelope.
        """
        command = str(args.get("command") or "")
        cwd = args.get("cwd")
        cwd_str = cwd if isinstance(cwd, str) and cwd else None
        shell = str(args.get("shell") or "auto")
        timeout_raw = args.get("timeout")
        timeout = (
            float(timeout_raw)
            if isinstance(timeout_raw, (int, float))
            else None
        )
        return self._exec_streaming_port.stream(
            command=command,
            cwd=cwd_str,
            shell=shell,
            timeout=timeout,
        )
