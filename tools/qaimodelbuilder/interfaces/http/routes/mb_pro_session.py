"""MB Pro (Model Builder Pro) session-control routes — /api/mb-pro-session/*.

These routes back the chat composer's「Pro / 增强」mode toolbar buttons:

* ``POST /api/mb-pro-session/connect``   — establish the session + SSE long-poll
* ``POST /api/mb-pro-session/disconnect``— tear down the session
* ``GET  /api/mb-pro-session/state``     — current connection snapshot
* ``GET  /api/mb-pro-session/version``   — remote agent version info

The session is owned by a process-singleton ``SessionManager`` in the chat
infrastructure layer; the chat turn (``query::mb_pro`` hint →
``SessionQueryServiceAdapter``) reuses that same live session, so these routes
only manage lifecycle — they do NOT carry conversation messages (those flow
through the normal chat WS/SSE).

Layering (import-linter ``interfaces-stays-thin``): this module must NOT import
``qai.chat.infrastructure``. The session-lifecycle facade
(:class:`~apps.api._mb_pro_session_bridge.MbProSessionController`) is composed at
the apps/api composition root and injected onto ``container.mb_pro_session``;
these handlers consume it by duck-typing — exactly how the CEBot query-services
route reads ``container`` without reaching into infrastructure.

Lifecycle is **user-controlled** (mb-pro-integration-plan.md decision §2.9):
the user clicks 连接 / 断开 in the Pro toolbar; the chat turn never auto-creates
a session.

internal-only (four-layer defence, layer 1 — runtime gate): the controller is
``None`` on external editions (built only when ``settings.is_internal``), so
every handler short-circuits to a 404-equivalent / disabled response.

CSRF: the non-GET handlers are subject to the global double-submit-cookie
``CsrfMiddleware``; the frontend mirrors the ``qai_csrf`` cookie into the
``X-QAI-CSRF`` header on connect/disconnect (read-only GET state/version are
exempt). No extra handling is needed here — the middleware enforces it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover
    from apps.api.di import Container


# ---------------------------------------------------------------------------
# Schemas (module level — FastAPI body-param resolution discipline)
# ---------------------------------------------------------------------------


class ConnectRequest(BaseModel):
    """Body for ``POST /api/mb-pro-session/connect``.

    ``tab_id`` binds the session to THIS chat tab (each tab owns an independent
    MB Pro session so histories never mix and each reconnects/restores by its
    own ``session_id``). ``tab_id`` — not ``conversation_id`` — is the key
    because a brand-new chat has no conversation id until its first message,
    while the Pro toolbar's「连接」happens before that; the chat turn keys its
    session lookup off ``tab_id`` too, so the two agree. The remaining fields
    are optional: an empty body (besides ``tab_id``) connects to the
    factory-default host (``internal_config.toml [query_services.mb_pro]``).
    The Pro settings dialog overrides ``agent_url`` / ``insecure`` for a custom
    host and ``session_id`` to re-attach to this tab's existing remote session
    (history restore).

    ``conversation_id`` (optional, appended): when present, the controller
    consumes the Agent's connect-time greeting burst and persists its
    self-intro as an assistant message bound to this conversation
    (see ``PersistMbProGreetingUseCase``). The frontend ensures a conversation
    exists before calling connect on a brand-new tab so this anchor is
    available. Omitted ⇒ greeting persistence + broadcast are skipped (the
    backend still completes the session-level connect).
    """

    tab_id: str
    agent_url: str | None = None
    session_id: str | None = None
    insecure: bool | None = None
    conversation_id: str | None = None


class DisconnectRequest(BaseModel):
    """Body for ``POST /api/mb-pro-session/disconnect`` — which tab."""

    tab_id: str


class SessionStateResponse(BaseModel):
    """Snapshot of the current MB Pro session connection."""

    connected: bool
    session_id: str | None = None
    agent_url: str | None = None
    insecure: bool = False


class VersionResponse(BaseModel):
    """Remote agent version info (opaque passthrough)."""

    version: dict[str, Any]


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def _controller(container: "Container") -> Any | None:
    """Return the injected MB Pro session controller, or ``None`` (external)."""
    return getattr(container, "mb_pro_session", None)


def build_router(*, container: "Container") -> APIRouter:
    """Build the MB Pro session-control router (internal-only behaviour)."""
    router = APIRouter(prefix="/api/mb-pro-session", tags=["mb-pro"])

    @router.post("/connect", response_model=SessionStateResponse)
    async def connect(body: ConnectRequest) -> SessionStateResponse:
        ctrl = _controller(container)
        if ctrl is None:
            raise HTTPException(status_code=404, detail="MB Pro not available")
        try:
            state = await ctrl.connect(
                tab_id=body.tab_id,
                agent_url=body.agent_url,
                session_id=body.session_id,
                insecure=body.insecure,
                conversation_id=body.conversation_id,
            )
        except RuntimeError as exc:
            # The bridge raises a structured ``MbProProbeError`` (a
            # RuntimeError subclass carrying ``code`` + ``details``) for the
            # auto-probe pool outcomes, and a plain ``RuntimeError`` for
            # everything else (per-port connect failures, "not configured").
            #
            # We DUCK-TYPE off ``code`` rather than importing the bridge's
            # exception type — the interfaces layer must not depend on
            # ``apps.api`` (import-linter ``interfaces-stays-thin``); it already
            # consumes the controller by duck-typing for the same reason.
            #
            # Structured probe errors are returned as a machine-readable body
            # (``{code, message, details}``) so the FRONTEND renders a localized
            # (i18n) message from ``code`` — the backend ships DATA, not a
            # pre-formatted user sentence. Status is derived from the code:
            #   * ``mb_pro.pool_all_busy``    → 503 (temporary exhaustion)
            #   * ``mb_pro.pool_all_offline`` → 502 (upstream down)
            #   * anything else               → 502
            code = getattr(exc, "code", "")
            if isinstance(code, str) and code.startswith("mb_pro."):
                details = getattr(exc, "details", {}) or {}
                status = 503 if code == "mb_pro.pool_all_busy" else 502
                raise HTTPException(
                    status_code=status,
                    detail={
                        "code": code,
                        "message": str(exc),
                        "details": details,
                    },
                ) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return SessionStateResponse(**state)

    @router.post("/disconnect", response_model=SessionStateResponse)
    async def disconnect(body: DisconnectRequest) -> SessionStateResponse:
        ctrl = _controller(container)
        if ctrl is None:
            raise HTTPException(status_code=404, detail="MB Pro not available")
        state = await ctrl.disconnect(tab_id=body.tab_id)
        return SessionStateResponse(**state)

    @router.get("/state", response_model=SessionStateResponse)
    async def state(tab_id: str) -> SessionStateResponse:
        ctrl = _controller(container)
        if ctrl is None:
            return SessionStateResponse(connected=False)
        return SessionStateResponse(
            **ctrl.get_state(tab_id=tab_id)
        )

    @router.get("/version", response_model=VersionResponse)
    async def version(
        agent_url: str | None = None,
        insecure: bool | None = None,
    ) -> VersionResponse:
        ctrl = _controller(container)
        if ctrl is None:
            raise HTTPException(status_code=404, detail="MB Pro not available")
        try:
            info = await ctrl.fetch_version(agent_url=agent_url, insecure=insecure)
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — surface as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return VersionResponse(version=info)

    return router


__all__ = ["build_router"]
