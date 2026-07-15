"""Use case: directly execute a tool **without** an active coding session.

PR-108c (S7.5 L1) — backs the universal ``POST /api/tool_execute`` and
``POST /api/tool_execute_stream`` routes catalogued by the
``S8-parity-audit.md`` **P1-B18 KEEP** decision.  In the legacy
``backend/main.py`` the corresponding endpoints (lines 6396 and 6461)
sit outside the AI-coding session lifecycle: they let the WebUI run
a single tool round-trip from a UI button (or feed a tool call back
to a model that emitted one), without spawning / restoring a
``CodingSession`` aggregate.

This use case translates that semantics into the new BC:

* takes a free ``tool_name`` + ``args`` pair;
* invokes the configured :class:`ToolBridgePort` (the same registry
  the per-session :class:`InvokeToolUseCase` uses → identical 9
  production tools shipped by PR-101);
* returns the raw :class:`ToolBridgeResult` plus a model-facing
  rendered string and a head+tail preview suitable for feeding back
  to the LLM without polluting the context window;
* does NOT start / mutate / persist a :class:`CodingSession`;
* does NOT consult :class:`PermissionDecisionPort` — the legacy
  endpoint was likewise unauthenticated for tool execution because
  it surfaces only inside an authenticated WebUI session.  The
  ``allow_exec_tool`` flag check that the legacy route owned will
  be re-implemented in PR-501..504 (security lane) once the
  ``ToolPolicy`` adapter lands; for now this use case is the
  same trust level as :class:`InvokeToolUseCase`.

The head+tail truncation logic is intentionally self-contained here
(an in-memory, zero-dependency implementation) because the
``layered-ai_coding`` import-linter contract forbids the application
layer from depending on infrastructure.  It shares the same byte
boundary semantics with PR-108c-defined defaults as the
infrastructure-layer persisted variant
(:class:`qai.ai_coding.infrastructure.tools.tool_result_store`), but
this use case needs no persistence and therefore keeps its own
preview-only slice.

Cross-context isolation: imports only ``qai.ai_coding.{application,
domain}`` plus the stdlib.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from qai.ai_coding.application.ports import ToolBridgePort, ToolBridgeResult
from qai.ai_coding.domain import ToolName

# ---------------------------------------------------------------------------
# Constants — duplicated intentionally (see module docstring).
# ---------------------------------------------------------------------------

DEFAULT_TOOL_RESULT_THRESHOLD_BYTES: int = 16 * 1024
DEFAULT_TOOL_RESULT_HEAD_BYTES: int = 8 * 1024
DEFAULT_TOOL_RESULT_TAIL_BYTES: int = 4 * 1024


# ---------------------------------------------------------------------------
# Command + result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteToolDirectlyCommand:
    """Input for :class:`ExecuteToolDirectlyUseCase`.

    ``model_id`` and ``current_used_tokens`` mirror the legacy
    ``ToolExecuteRequest`` payload (``backend/main.py:1947``); they're
    advisory — the use case does not adapt the threshold to them
    (parity with the legacy default-path semantics).  Future tuning
    can read these values without breaking the wire format.
    """

    tool_name: ToolName
    args: dict[str, Any] = field(default_factory=dict)
    model_id: str | None = None
    current_used_tokens: int | None = None
    threshold_bytes: int = DEFAULT_TOOL_RESULT_THRESHOLD_BYTES
    head_bytes: int = DEFAULT_TOOL_RESULT_HEAD_BYTES
    tail_bytes: int = DEFAULT_TOOL_RESULT_TAIL_BYTES


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteToolDirectlyResult:
    """Outcome of :meth:`ExecuteToolDirectlyUseCase.execute`.

    Mirrors the legacy ``backend/main.py:6396`` wire envelope plus
    a few extra status fields:

    * ``raw_result`` — the structured tool body the bridge returned;
    * ``rendered`` — full string suitable for UI display (never
      truncated);
    * ``preview`` — head+tail summary suitable for feeding to the
      model (= ``rendered`` when below threshold);
    * ``ok`` / ``error_code`` — same shape as :class:`ToolBridgeResult`;
    * ``tool_name`` — echoed back for client-side correlation;
    * ``truncated`` — ``True`` when ``preview`` is shorter than
      ``rendered``;
    * ``total_bytes`` / ``omitted_bytes`` — UTF-8 lengths so clients
      can render a "view full output" hint.
    """

    tool_name: str
    ok: bool
    raw_result: dict[str, Any] | None
    error_code: str | None
    rendered: str
    preview: str
    truncated: bool
    total_bytes: int
    omitted_bytes: int


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def build_preview(
    text: str,
    *,
    threshold_bytes: int,
    head_bytes: int,
    tail_bytes: int,
) -> tuple[str, int, int, bool]:
    """Render head+tail preview when ``text`` exceeds ``threshold_bytes``.

    Public application-layer helper (also reused by the
    ``/api/tool_execute_stream`` route to summarise the streamed exec output
    for the LLM, mirroring this use case's behaviour).

    Returns ``(preview, total_bytes, omitted_bytes, truncated)``.
    Decoding is byte-aware so we don't slice in the middle of a
    multi-byte CJK character.
    """
    encoded = text.encode("utf-8")
    total = len(encoded)
    if total <= threshold_bytes:
        return text, total, 0, False

    if total <= head_bytes + tail_bytes:
        return text, total, 0, False

    head = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
    omitted = total - head_bytes - tail_bytes
    omit_marker = (
        f"\n\n... [omitted {omitted:,} bytes / total {total:,} bytes] ...\n\n"
    )
    preview = f"{head}{omit_marker}{tail}"
    return preview, total, omitted, True


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class ExecuteToolDirectlyUseCase:
    """Execute one tool round-trip via :class:`ToolBridgePort`.

    Construction parameters
    -----------------------
    * ``tool_bridge`` — the same :class:`ToolBridgePort` instance the
      per-session :class:`InvokeToolUseCase` uses.  Wired from
      ``container.ai_coding.tool_bridge`` in
      ``apps/api/_ai_coding_di.py``.
    """

    def __init__(self, *, tool_bridge: ToolBridgePort) -> None:
        self._tool_bridge = tool_bridge

    @property
    def tool_bridge(self) -> ToolBridgePort:
        return self._tool_bridge

    async def execute(
        self, command: ExecuteToolDirectlyCommand
    ) -> ExecuteToolDirectlyResult:
        try:
            bridge_result: ToolBridgeResult = await self._tool_bridge.invoke(
                tool_name=command.tool_name,
                args=dict(command.args),
            )
        except Exception as exc:  # noqa: BLE001 — surface as bridge failure
            error_text = f"[tool_error] tool_bridge raised: {exc!r}"
            preview, total, omitted, truncated = build_preview(
                error_text,
                threshold_bytes=command.threshold_bytes,
                head_bytes=command.head_bytes,
                tail_bytes=command.tail_bytes,
            )
            return ExecuteToolDirectlyResult(
                tool_name=str(command.tool_name),
                ok=False,
                raw_result=None,
                error_code="ai_coding.tool_bridge_error",
                rendered=error_text,
                preview=preview,
                truncated=truncated,
                total_bytes=total,
                omitted_bytes=omitted,
            )

        # PR-108a Decision #5: PR-101's tool handlers report failures
        # via the inner ``{"ok": false, "error_code": ...}`` envelope
        # while the bridge itself reports ``ok=True``.  Mirror the
        # harness's flattening so callers (route layer + downstream
        # chat handler) only ever check one boolean.
        effective_ok = bool(bridge_result.ok)
        effective_error_code = bridge_result.error_code
        if (
            effective_ok
            and isinstance(bridge_result.result, dict)
            and bridge_result.result.get("ok") is False
        ):
            effective_ok = False
            inner_code = bridge_result.result.get("error_code")
            if isinstance(inner_code, str) and inner_code:
                effective_error_code = inner_code
            else:
                effective_error_code = (
                    effective_error_code or "ai_coding.tool_failed"
                )

        rendered = self._render_for_model(
            bridge_result, effective_ok=effective_ok
        )
        preview, total, omitted, truncated = build_preview(
            rendered,
            threshold_bytes=command.threshold_bytes,
            head_bytes=command.head_bytes,
            tail_bytes=command.tail_bytes,
        )
        return ExecuteToolDirectlyResult(
            tool_name=str(command.tool_name),
            ok=effective_ok,
            raw_result=bridge_result.result,
            error_code=effective_error_code,
            rendered=rendered,
            preview=preview,
            truncated=truncated,
            total_bytes=total,
            omitted_bytes=omitted,
        )

    @staticmethod
    def _render_for_model(
        result: ToolBridgeResult, *, effective_ok: bool | None = None
    ) -> str:
        """Render a :class:`ToolBridgeResult` to a model-readable string.

        Tools return structured dicts (PR-101 contract).  The legacy
        WebUI tool-execute path expects a single string the model can
        read; we render the raw_result by:

        * preferring a top-level ``text`` / ``stdout`` / ``output`` /
          ``content`` key when present (most tools follow this
          convention);
        * otherwise serialising the dict as pretty JSON;
        * prefixing failures with ``[tool_error] <code>`` so callers
          that detect failure with a string check (parity with
          :class:`RegistryBackedToolBridge`) keep working.

        ``effective_ok`` (when supplied) overrides
        :attr:`ToolBridgeResult.ok` so the renderer honours the
        flattened inner-envelope status decided by :meth:`execute`.
        """
        ok = effective_ok if effective_ok is not None else result.ok
        if ok:
            body = result.result if result.result is not None else {}
            if isinstance(body, dict):
                for key in ("text", "stdout", "output", "content"):
                    value = body.get(key)
                    if isinstance(value, str) and value:
                        return value
            return json.dumps(body, ensure_ascii=False, indent=2)

        message = ""
        code = result.error_code
        if isinstance(result.result, dict):
            inner_code = result.result.get("error_code")
            if isinstance(inner_code, str) and inner_code:
                code = inner_code
            for key in ("error", "message", "text"):
                value = result.result.get(key)
                if isinstance(value, str) and value:
                    message = value
                    break
        prefix = "[tool_error]"
        code = code or "ai_coding.tool_failed"
        if message:
            return f"{prefix} {code}: {message}"
        return f"{prefix} {code}"


__all__ = [
    "DEFAULT_TOOL_RESULT_HEAD_BYTES",
    "DEFAULT_TOOL_RESULT_TAIL_BYTES",
    "DEFAULT_TOOL_RESULT_THRESHOLD_BYTES",
    "ExecuteToolDirectlyCommand",
    "ExecuteToolDirectlyResult",
    "ExecuteToolDirectlyUseCase",
    "build_preview",
]
