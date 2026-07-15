"""Universal tool-execute routes (``_register_universal_tool_routes``).

The 2 ``POST /api/tool_execute(_stream)`` routes mounted on the
aggregate (NOT under the /api/cc or /api/oc sub-routers).  Extracted
verbatim from the former single-file ``ai_coding.py`` (zero behaviour
change).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from qai.ai_coding.application.use_cases.execute_tool_directly import (
    DEFAULT_TOOL_RESULT_HEAD_BYTES,
    DEFAULT_TOOL_RESULT_TAIL_BYTES,
    DEFAULT_TOOL_RESULT_THRESHOLD_BYTES,
    ExecuteToolDirectlyCommand,
    build_preview,
)
from qai.ai_coding.domain import ToolName

from ._dto import ToolExecuteRequest, ToolExecuteResponse

if TYPE_CHECKING:  # pragma: no cover
    from apps.api.di import Container


def _register_universal_tool_routes(
    router: APIRouter,
    *,
    container: "Container",
) -> None:
    """Attach the 2 universal ``POST /api/tool_execute(_stream)`` routes.

    These routes (PR-108c, P1-B18 KEEP) are the new BC's port of the
    legacy ``backend/main.py:6396 /api/tool_execute`` and
    ``backend/main.py:6461 /api/tool_execute_stream`` endpoints.
    Unlike the per-session ``/api/{cc|oc}/sessions/{id}/tools/invoke``
    routes (which require an active :class:`CodingSession`), these
    routes accept a free ``tool_name`` + ``arguments`` pair and run
    one tool round-trip directly through the registry that PR-101
    populated with the 9 production tool handlers.

    Both routes emit the legacy wire shape so the WebUI / chat
    handler that previously consumed them continues to work without
    a payload migration.

    The streaming variant returns a follow-up SSE envelope built
    around the single bridge call: ``start`` → ``done`` (with the
    full result) → ``[DONE]`` sentinel.  Tools that natively stream
    (``exec``) will get richer streaming once a streaming-capable
    :class:`ToolBridgePort` is wired (out-of-scope for PR-108c).
    """
    services = container.ai_coding

    @router.post("/api/tool_execute", response_model=ToolExecuteResponse)
    async def universal_tool_execute(
        body: ToolExecuteRequest,
    ) -> ToolExecuteResponse:
        result = await services.execute_tool_directly_use_case.execute(
            ExecuteToolDirectlyCommand(
                tool_name=ToolName(value=body.name),
                args=dict(body.arguments),
                model_id=body.model_id,
                current_used_tokens=body.current_used_tokens,
            )
        )
        return ToolExecuteResponse(
            result=result.rendered,
            model_result=result.preview,
            tool_name=result.tool_name,
            success=result.ok,
            truncated=result.truncated,
            stored_path=None,  # in-memory path; persisted variant ships in PR-501+
            error_code=result.error_code,
        )

    @router.post("/api/tool_execute_stream")
    async def universal_tool_execute_stream(
        body: ToolExecuteRequest,
    ) -> StreamingResponse:
        # Snapshot the request body *before* entering the streaming
        # generator — fastapi consumes the body lazily once the
        # generator starts pulling, but the generator captures it
        # via closure so we can pass it through cleanly.
        cmd = ExecuteToolDirectlyCommand(
            tool_name=ToolName(value=body.name),
            args=dict(body.arguments),
            model_id=body.model_id,
            current_used_tokens=body.current_used_tokens,
        )

        async def _body_iter() -> AsyncIterator[bytes]:
            # Frame 1: start.  Mirrors legacy ``{"type":"start","tool":...}``.
            start_payload = {"type": "start", "tool": cmd.tool_name.value}
            yield f"data: {json.dumps(start_payload, ensure_ascii=False)}\n\n".encode("utf-8")

            # 落点5: the ``exec`` tool streams real-time stdout/stderr.
            # V1 surfaced live output as ``{type:"output"}`` SSE frames
            # (``backend/tools/_exec.py:1010``).  We restore that here via
            # the ai_coding ``StreamToolExecUseCase`` → ``ExecStreamingPort``
            # so the route never imports the infrastructure exec engine
            # (the ``interfaces-stays-thin`` / ``context-isolation``
            # import-linter contracts forbid it).  Every other tool has no
            # incremental output, so it keeps the one-shot ``done`` envelope
            # via ``execute_tool_directly_use_case``.
            stream_uc = getattr(services, "stream_tool_exec_use_case", None)
            if stream_uc is not None and stream_uc.applies_to(cmd.tool_name.value):
                try:
                    chunk_iter, accumulator = stream_uc.stream(
                        args=dict(cmd.args)
                    )
                    async for chunk in chunk_iter:
                        if chunk.kind == "output":
                            if not chunk.data:
                                continue
                            out_payload = {"type": "output", "data": chunk.data}
                            yield f"data: {json.dumps(out_payload, ensure_ascii=False)}\n\n".encode("utf-8")
                        elif chunk.kind == "cap_reached":
                            cap_payload = {"type": "cap_reached"}
                            yield f"data: {json.dumps(cap_payload, ensure_ascii=False)}\n\n".encode("utf-8")
                        # ``started`` / ``terminated`` chunks are folded
                        # into the start / done envelopes below.
                except Exception as exc:  # noqa: BLE001 — surface as SSE error
                    err = {"type": "error", "message": f"[tool_error] {exc!r}"}
                    yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return

                # Final ``done`` envelope built from the streamed output so
                # the wire shape stays identical to the one-shot path
                # (``result`` / ``model_result`` / ``truncated``).  The
                # accumulator is populated once the iterator drains.
                full_output = accumulator.full_output or ""
                # V1 parity (backend/main.py:6535 ``_make_model_result``) +
                # alignment with this file's NON-streaming path (which feeds the
                # model ``result.preview``, not the full body): ``result`` is the
                # complete output for the UI, but ``model_result`` fed back to the
                # LLM must be a head+tail SUMMARY so a huge stdout cannot blow the
                # model's context. The prior code put the full output in BOTH,
                # diverging from V1 and from the non-streaming branch below.
                model_result, _total, _omitted, summary_truncated = build_preview(
                    full_output,
                    threshold_bytes=DEFAULT_TOOL_RESULT_THRESHOLD_BYTES,
                    head_bytes=DEFAULT_TOOL_RESULT_HEAD_BYTES,
                    tail_bytes=DEFAULT_TOOL_RESULT_TAIL_BYTES,
                )
                # ``truncated`` reflects either the live 50KB cap_reached notice
                # OR the head+tail summary applied here.
                truncated = (
                    bool(getattr(accumulator, "truncated", False))
                    or summary_truncated
                )
                done_payload = {
                    "type": "done",
                    "result": full_output,
                    "model_result": model_result,
                    "tool_name": cmd.tool_name.value,
                    "success": (getattr(accumulator, "exit_code", 0) == 0)
                    and not getattr(accumulator, "timed_out", False),
                    "truncated": truncated,
                }
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
                return

            # Non-streaming tools: one-shot ``done`` envelope (unchanged).
            try:
                result = await services.execute_tool_directly_use_case.execute(cmd)
            except Exception as exc:  # noqa: BLE001 — surface as SSE error
                err = {"type": "error", "message": f"[tool_error] {exc!r}"}
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
                return

            # Frame 2: done.  Mirrors legacy ``{"type":"done","result":...,
            # "model_result":..., "truncated":...}``.
            done_payload = {
                "type": "done",
                "result": result.rendered,
                "model_result": result.preview,
                "tool_name": result.tool_name,
                "success": result.ok,
                "truncated": result.truncated,
            }
            if result.error_code:
                done_payload["error_code"] = result.error_code
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

        return StreamingResponse(
            _body_iter(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- tool_execute (WS) ------------------------------------------------

    async def _safe_send_json(ws: WebSocket, data: dict) -> bool:  # type: ignore[type-arg]
        try:
            await ws.send_json(data)
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return False

    @router.websocket("/api/tool-execute/ws")
    async def tool_execute_ws(websocket: WebSocket) -> None:
        """WebSocket variant of ``POST /api/tool_execute_stream``.

        The client sends the request as the FIRST WebSocket message
        (JSON with ``tool_name`` and ``arguments``). The server then
        streams results using the standard wire format:
        ``{"type": "frame", "event": "<type>", "payload": {...}}``
        followed by ``{"type": "done"}``.
        """
        await websocket.accept()

        # 1. Read first message as the request (10s timeout).
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except asyncio.TimeoutError:
            await _safe_send_json(
                websocket,
                {"type": "error", "code": "timeout", "message": "No request received within 10s"},
            )
            try:
                await websocket.close(code=4408)
            except (RuntimeError, WebSocketDisconnect):
                pass
            return
        except WebSocketDisconnect:
            return
        except Exception:
            return

        # 2. Validate request.
        tool_name = raw.get("tool_name") if isinstance(raw, dict) else None
        arguments = raw.get("arguments", {}) if isinstance(raw, dict) else {}
        model_id = raw.get("model_id") if isinstance(raw, dict) else None
        current_used_tokens = raw.get("current_used_tokens", 0) if isinstance(raw, dict) else 0

        if not tool_name:
            await _safe_send_json(
                websocket,
                {"type": "error", "code": "invalid_request", "message": "tool_name required"},
            )
            try:
                await websocket.close(code=4400)
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        cmd = ExecuteToolDirectlyCommand(
            tool_name=ToolName(value=tool_name),
            args=dict(arguments) if arguments else {},
            model_id=model_id,
            current_used_tokens=current_used_tokens or 0,
        )

        # 3. Send start frame.
        if not await _safe_send_json(
            websocket,
            {"type": "frame", "event": "start", "payload": {"tool": cmd.tool_name.value}},
        ):
            return

        # 4. Stream execution — reuse the same logic as the SSE handler.
        stream_uc = getattr(services, "stream_tool_exec_use_case", None)
        if stream_uc is not None and stream_uc.applies_to(cmd.tool_name.value):
            try:
                chunk_iter, accumulator = stream_uc.stream(args=dict(cmd.args))
                async for chunk in chunk_iter:
                    if chunk.kind == "output":
                        if not chunk.data:
                            continue
                        if not await _safe_send_json(
                            websocket,
                            {"type": "frame", "event": "output", "payload": {"data": chunk.data}},
                        ):
                            return
                    elif chunk.kind == "cap_reached":
                        if not await _safe_send_json(
                            websocket,
                            {"type": "frame", "event": "cap_reached", "payload": {}},
                        ):
                            return
            except Exception as exc:  # noqa: BLE001
                await _safe_send_json(
                    websocket,
                    {"type": "error", "code": "tool_error", "message": f"[tool_error] {exc!r}"},
                )
                try:
                    await websocket.close(code=1011)
                except (RuntimeError, WebSocketDisconnect):
                    pass
                return

            # Build done envelope from streamed output.
            full_output = accumulator.full_output or ""
            model_result, _total, _omitted, summary_truncated = build_preview(
                full_output,
                threshold_bytes=DEFAULT_TOOL_RESULT_THRESHOLD_BYTES,
                head_bytes=DEFAULT_TOOL_RESULT_HEAD_BYTES,
                tail_bytes=DEFAULT_TOOL_RESULT_TAIL_BYTES,
            )
            truncated = (
                bool(getattr(accumulator, "truncated", False))
                or summary_truncated
            )
            done_payload = {
                "result": full_output,
                "model_result": model_result,
                "tool_name": cmd.tool_name.value,
                "success": (getattr(accumulator, "exit_code", 0) == 0)
                and not getattr(accumulator, "timed_out", False),
                "truncated": truncated,
            }
            await _safe_send_json(
                websocket,
                {"type": "frame", "event": "done", "payload": done_payload},
            )
            await _safe_send_json(websocket, {"type": "done"})
            try:
                await websocket.close(code=1000)
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        # Non-streaming tools: one-shot execution.
        try:
            result = await services.execute_tool_directly_use_case.execute(cmd)
        except Exception as exc:  # noqa: BLE001
            await _safe_send_json(
                websocket,
                {"type": "error", "code": "tool_error", "message": f"[tool_error] {exc!r}"},
            )
            try:
                await websocket.close(code=1011)
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        done_payload = {
            "result": result.rendered,
            "model_result": result.preview,
            "tool_name": result.tool_name,
            "success": result.ok,
            "truncated": result.truncated,
        }
        if result.error_code:
            done_payload["error_code"] = result.error_code
        await _safe_send_json(
            websocket,
            {"type": "frame", "event": "done", "payload": done_payload},
        )
        await _safe_send_json(websocket, {"type": "done"})
        try:
            await websocket.close(code=1000)
        except (RuntimeError, WebSocketDisconnect):
            pass
