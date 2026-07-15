"""Apps-layer bridge: MB Pro session-lifecycle controller.

The chat composer's「Pro / 增强」mode exposes user-controlled
connect / disconnect / version buttons (mb-pro-integration-plan.md §2.9). The
HTTP routes for those buttons live in ``interfaces.http.routes.mb_pro_session``,
but the ``interfaces.http`` layer may only depend on application ports +
platform (import-linter ``interfaces-stays-thin`` contract) — it must NOT reach
into ``qai.chat.infrastructure`` (where the
:class:`~qai.chat.infrastructure.query_service.session_adapter.SessionManager`
per-tab registry + the edition descriptor live).

This bridge is the composition-root seam (apps/api is allowed to import both
``qai.chat.infrastructure`` and ``qai.platform``): it builds a small
``MbProSessionController`` object that the routes consume by duck-typing off
``container.mb_pro_session`` — exactly mirroring how ``_query_service_bridge``
composes the chat ``query_stream_factory`` from edition config + infrastructure
without leaking either into the chat context.

internal-only: the controller is only built when ``settings.is_internal`` is
true; on external editions ``build_mb_pro_session_controller`` returns ``None``
(the ``query_service`` subpackage + edition config are physically excluded), so
the routes short-circuit to a 404-equivalent disabled response.

All imports of the excluded packages are **local to the internal-gated body**
so a stripped external tree never triggers an ImportError at module load.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from qai.platform.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    pass

__all__ = [
    "MbProProbeError",
    "MbProSessionController",
    "build_mb_pro_session_controller",
]

_log = get_logger(__name__)


class MbProProbeError(RuntimeError):
    """Structured auto-probe failure raised by :func:`_find_idle_agent_url`.

    Carries a machine-readable ``code`` + a ``details`` mapping so the
    interfaces layer maps it to the right HTTP status AND the frontend can
    render a localized (i18n) message from the code instead of transporting a
    pre-formatted Chinese sentence (PROJECT-RULES §3.9 / i18n: user-facing text
    is the frontend's job, the backend ships DATA). Subclasses ``RuntimeError``
    so existing ``except RuntimeError`` handlers still catch it (the "not
    configured" path and generic per-port failures keep working unchanged).

    Codes (stable contract — the frontend switches on these):
      * ``mb_pro.pool_all_offline`` — every port unreachable (→ 502).
      * ``mb_pro.pool_all_busy``    — every port reachable but busy (→ 503);
        ``details["busy_count"]`` = how many machines are busy.
    """

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


class MbProSessionController:
    """Thin lifecycle facade over the per-tab MB Pro session registry.

    Each chat TAB owns an INDEPENDENT MB Pro session (the server keys history
    off ``session_id``; concurrent sessions are supported natively), so every
    method takes a ``tab_id`` and operates on THAT tab's :class:`SessionManager`
    from the registry. ``tab_id`` (not ``conversation_id``) is the key because a
    brand-new chat has no conversation id until its first message while the Pro
    toolbar's「连接」happens before that — and the chat turn keys its session
    lookup off ``tab_id`` too, so the two agree. Rebuilds the MB Pro descriptor
    from edition config on each call (so a config change takes effect without a
    restart). Methods return plain dicts / raise :class:`RuntimeError` so the
    interfaces layer can map them to HTTP responses without importing any
    infrastructure type.
    """

    __slots__ = (
        "_descriptor_factory",
        "_probe_config_factory",
        "_get_manager",
        "_peek_manager",
        "_drop_manager",
        "_greeting_use_case",
    )

    def __init__(
        self,
        *,
        descriptor_factory: Any,
        get_manager: Any,
        peek_manager: Any,
        drop_manager: Any,
        greeting_use_case: Any = None,
        probe_config_factory: Any = None,
    ) -> None:
        self._descriptor_factory = descriptor_factory
        self._probe_config_factory = probe_config_factory
        self._get_manager = get_manager
        self._peek_manager = peek_manager
        self._drop_manager = drop_manager
        self._greeting_use_case = greeting_use_case

    @staticmethod
    def _snapshot(state: Any) -> dict[str, Any]:
        return {
            "connected": state.connected,
            "session_id": state.session_id,
            "agent_url": state.agent_url,
            "insecure": state.insecure,
        }

    @staticmethod
    def _disconnected() -> dict[str, Any]:
        return {
            "connected": False,
            "session_id": None,
            "agent_url": None,
            "insecure": False,
        }

    def get_state(self, *, tab_id: str) -> dict[str, Any]:
        # Read-only: never materialise a manager for a tab that never connected
        # (peek → None ⇒ a clean disconnected snapshot).
        mgr = self._peek_manager(tab_id)
        if mgr is None:
            return self._disconnected()
        return self._snapshot(mgr.get_state())

    async def connect(
        self,
        *,
        tab_id: str,
        agent_url: str | None,
        session_id: str | None,
        insecure: bool | None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        descriptor = self._descriptor_factory()
        if descriptor is None:
            raise RuntimeError("MB Pro not configured")

        # Auto-probe: when the frontend calls connect WITHOUT specifying
        # ``agent_url`` AND WITHOUT a ``session_id`` hint (fresh session on a
        # new tab), transparently pick an idle port from the pool. If the tab
        # has a remembered session_id (reconnect for history restore), respect
        # it — the user's history lives on that specific port, so we do NOT
        # auto-probe on reconnects. If no pool is configured
        # (``_probe_config_factory`` returns None), the descriptor's single
        # ``endpoint`` is used as-is (backward compatible).
        resolved_agent_url = agent_url
        if resolved_agent_url is None and not session_id:
            probe_cfg = (
                self._probe_config_factory()
                if self._probe_config_factory is not None
                else None
            )
            if probe_cfg is not None:
                host, ports, timeout = probe_cfg
                resolved_agent_url = await _find_idle_agent_url(
                    descriptor=descriptor,
                    insecure=insecure,
                    host=host,
                    ports=ports,
                    timeout=timeout,
                )

        # Lazily create THIS tab's manager (connecting is the user's explicit
        # action). Other tabs' sessions are untouched — no displacement, so the
        # UI no longer needs a "disconnect the other one" prompt.
        mgr = self._get_manager(tab_id)
        state = await mgr.connect(
            descriptor=descriptor,
            agent_url=resolved_agent_url,
            session_id_hint=session_id,
            insecure=insecure,
        )
        # Greeting persistence + broadcast (fire-and-forget). On a fresh session
        # the remote Agent pushes a 3-event greeting burst (``queue_state`` →
        # ``agent_ready`` → ``turn`` with self-intro); without consumption it
        # would be discarded by the next turn's ``flush_pending_events``. We
        # drain it HERE, persist the assistant intro as a standalone message,
        # and broadcast frames so any subscriber sees it immediately.
        #
        # Only triggered on a brand-new session creation (no ``session_id``
        # hint): reconnect-by-sid attaches to an existing remote session that
        # already emitted its greeting once. Also requires a ``conversation_id``
        # — the persistence anchor — which the frontend ensures before
        # calling connect on a brand-new tab.
        if (
            state.connected
            and not session_id
            and conversation_id
            and self._greeting_use_case is not None
        ):
            # Reserve the broadcast slot SYNCHRONOUSLY — before the HTTP
            # response returns. The frontend's WS attach right after success
            # would otherwise race the fire-and-forget task and see
            # ``broadcaster.get(tab) is None`` → 404. Reserving here flips
            # ``get()`` to non-None instantly so the WS waits on ``replay``
            # while the background task drains + publishes.
            self._greeting_use_case.reserve_broadcast(
                tab_id=tab_id, conversation_id=conversation_id
            )

            from qai.chat.application.use_cases.mb_pro_greeting import (
                PersistMbProGreetingInput,
            )

            async def _greet() -> None:
                try:
                    await self._greeting_use_case.execute(
                        PersistMbProGreetingInput(
                            conversation_id=conversation_id,
                            tab_id=tab_id,
                        )
                    )
                except Exception:  # noqa: BLE001 — never break connect
                    _log.warning(
                        "mb_pro.greeting_use_case_failed",
                        tab_id=tab_id,
                        conversation_id=conversation_id,
                        exc_info=True,
                    )

            # Detach from the connect HTTP request: the user already sees
            # connection success when this returns; the greeting can land
            # whenever its 2-second drain completes.
            asyncio.create_task(_greet(), name=f"mb_pro_greeting[{tab_id}]")
        return self._snapshot(state)

    async def disconnect(self, *, tab_id: str) -> dict[str, Any]:
        mgr = self._peek_manager(tab_id)
        if mgr is None:
            return self._disconnected()
        state = await mgr.disconnect()
        # Forget the now-disconnected tab's manager so it does not leak an idle
        # entry in the registry (its remote session_id stays restorable until
        # the server's LRU evicts it; the frontend remembers it).
        self._drop_manager(tab_id)
        return self._snapshot(state)

    async def fetch_version(
        self,
        *,
        agent_url: str | None,
        insecure: bool | None,
    ) -> dict[str, Any]:
        # Version is a host-level probe (not tied to a tab/session); use a
        # throwaway manager so it never touches a live tab's one.
        descriptor = self._descriptor_factory()
        if descriptor is None:
            raise RuntimeError("MB Pro not configured")
        from qai.chat.infrastructure.query_service import SessionManager

        return await SessionManager().fetch_version(
            descriptor=descriptor,
            agent_url=agent_url,
            insecure=insecure,
        )


async def _find_idle_agent_url(
    *,
    descriptor: Any,
    insecure: bool | None,
    host: str,
    ports: tuple[int, ...],
    timeout: float,
    busy_retries: int = 2,
    busy_backoff_s: float = 2.0,
) -> str:
    """Probe the MB Pro pool and return the first idle port's URL.

    Each port hosts its own uvicorn process whose ``_global_builder`` singleton
    runs at most one job at a time. The ONLY reliable "is-this-port-idle"
    signal is the ``queue_state`` event that the remote emits as the first
    event of its connect-time greeting burst (verified live 2026-06-29). To
    read it we must actually create a session and consume that first event.

    Design (throwaway probes + fresh-connect on the winner):
      * For each port, spawn a throwaway ``SessionManager`` and race them
        concurrently. Each probe: create session → drain the first event → if
        it is a ``queue_state`` with ``busy=false`` it is a candidate. Whatever
        the outcome, the throwaway is disconnected before we return so the
        remote does not accumulate orphaned sessions.
      * As soon as ANY probe reports idle we cancel the still-running probes
        (they can only lose to the lowest-numbered idle port anyway) so we
        neither wait for the slowest port nor keep opening throwaway sessions
        we don't need — lower latency + less remote load.
      * The winner's URL is returned; the caller then does a NORMAL fresh
        ``connect`` against that URL (which triggers the standard greeting
        pipeline via :class:`PersistMbProGreetingUseCase`).

    Busy retry (temporary-exhaustion smoothing): GPU jobs are short-lived, so
    "all busy" is usually transient. Rather than fail immediately and make the
    user re-click, we re-probe up to ``busy_retries`` extra rounds, waiting
    ``busy_backoff_s`` between rounds. "All offline" is NOT retried (a down
    pool won't come back in seconds; fail fast so the user sees the real
    problem). Offline-vs-busy is re-evaluated each round: a port coming online
    mid-wait is picked up on the next round.

    Errors (raised as :class:`MbProProbeError` with a machine code so the
    frontend renders a localized message — see that class):
      * All ports offline → ``mb_pro.pool_all_offline`` (route → 502).
      * All ports reachable but busy after all retries →
        ``mb_pro.pool_all_busy`` with ``details["busy_count"]`` (route → 503).

    Host + port pool + timeout come from
    ``internal_config.toml [query_services.mb_pro]`` (``probe_host`` /
    ``probe_ports`` / ``probe_timeout_s``); the deployment topology is
    edition-config, not source (PROJECT-RULES §3.8.1).
    """
    # Local imports keep the module loadable on external editions (the
    # `query_service` subpackage is physically excluded there).
    from qai.chat.infrastructure.query_service import SessionManager

    async def _probe_one(port: int) -> tuple[int, str, bool] | None:
        """Return (port, url, is_idle) on success, ``None`` on unreachable.

        ``is_idle`` distinguishes "reachable but busy" from "reachable and
        idle" so the caller can tell the two error cases apart.
        """
        url = f"http://{host}:{port}"
        mgr = SessionManager()
        try:
            try:
                state = await mgr.connect(
                    descriptor=descriptor,
                    agent_url=url,
                    session_id_hint=None,
                    insecure=insecure,
                )
            except asyncio.CancelledError:
                raise  # a peer already found idle; propagate so finally cleans up
            except Exception:  # noqa: BLE001 — unreachable / handshake failure
                return None
            if not state.connected:
                return None
            # Read only the FIRST event: the greeting burst opens with
            # ``queue_state`` (per the remote's contract). If we somehow see a
            # different event first, treat it as "unknown → assume busy" to
            # be safe (won't wrongly claim an idle machine).
            is_idle = False
            async for event in mgr.drain_greeting(timeout=timeout):
                if event.get("type") == "queue_state":
                    is_idle = not bool(event.get("busy"))
                break  # only care about the FIRST event
            return (port, url, is_idle)
        finally:
            try:
                await mgr.disconnect()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                _log.debug("mb_pro.probe_disconnect_failed", port=port, exc_info=True)

    async def _probe_round() -> tuple[str | None, list[tuple[int, str, bool]]]:
        """One concurrent probe pass over all ports.

        Returns ``(idle_url_or_None, reachable_results)``. Cancels the
        remaining probes as soon as an idle one is seen (early exit). The
        returned ``idle_url`` is always the LOWEST-numbered idle port among the
        results collected so far, for deterministic routing.
        """
        tasks = {
            asyncio.ensure_future(_probe_one(p)): p for p in ports
        }
        reachable: list[tuple[int, str, bool]] = []
        found_idle = False
        try:
            for fut in asyncio.as_completed(list(tasks)):
                res = await fut
                if res is None:
                    continue
                reachable.append(res)
                if res[2]:  # is_idle → we can stop early
                    found_idle = True
                    break
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            # Let the cancellations settle so every throwaway session is
            # disconnected before we return (no orphaned remote sessions).
            await asyncio.gather(*tasks, return_exceptions=True)
        if found_idle:
            idle_ports = [r for r in reachable if r[2]]
            idle_ports.sort(key=lambda t: t[0])
            _port, url, _ = idle_ports[0]
            _log.info("mb_pro.autoprobe_picked", port=_port, url=url)
            return url, reachable
        return None, reachable

    attempts = max(1, busy_retries + 1)
    last_busy_count = 0
    for attempt in range(attempts):
        idle_url, reachable = await _probe_round()
        if idle_url is not None:
            return idle_url
        if not reachable:
            # Nothing answered at all → pool is down. Fail fast (do NOT retry;
            # a down pool won't recover within a few seconds).
            raise MbProProbeError(
                "mb_pro.pool_all_offline",
                "远端 Agent 全部离线",
                details={"port_count": len(ports)},
            )
        # Reachable but all busy. ``last_busy_count`` is the count of machines
        # that actually ANSWERED (reachable) on this round — NOT ``len(ports)``,
        # since some ports may be offline. Reporting the real busy count keeps
        # the user-facing number honest (e.g. "5 machines busy" when 3 of 8 are
        # simply down). Retry after a short backoff unless this was the last
        # attempt (temporary-exhaustion smoothing).
        last_busy_count = len(reachable)
        if attempt < attempts - 1:
            _log.info(
                "mb_pro.autoprobe_all_busy_retry",
                attempt=attempt + 1,
                busy_count=last_busy_count,
            )
            await asyncio.sleep(busy_backoff_s)
    raise MbProProbeError(
        "mb_pro.pool_all_busy",
        f"当前 {last_busy_count} 台机器全部繁忙，请稍后再试",
        details={"busy_count": last_busy_count},
    )


def build_mb_pro_session_controller(*, container: Any) -> MbProSessionController | None:
    """Build the controller, or ``None`` on external / unconfigured editions.

    The whole ``query_service`` subpackage + edition config are physically
    excluded from external artifacts; every import of them is **local to this
    internal-gated body** so a stripped external tree never triggers an
    ImportError when ``di`` imports this bridge at module load.
    """
    settings = getattr(container, "settings", None)
    if settings is None or not getattr(settings, "is_internal", False):
        return None

    try:
        from qai.platform.edition import get_query_services
        from qai.chat.infrastructure.query_service import (
            QueryServiceDescriptor,
            drop_session_manager,
            get_session_manager,
            peek_session_manager,
        )
    except Exception:  # pragma: no cover - excluded on external
        return None

    def _descriptor_factory() -> Any | None:
        fields = get_query_services().get("mb_pro")
        if not fields:
            return None
        endpoint = fields.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            return None

        def _path(key: str, default: str) -> str:
            raw = fields.get(key)
            return raw if isinstance(raw, str) and raw else default

        return QueryServiceDescriptor(
            service_id="mb_pro",
            display_name=str(fields.get("display_name") or "Model Builder Pro"),
            endpoint=endpoint,
            transport="session",
            insecure=bool(fields.get("insecure", False)),
            session_path=_path("session_path", "/session"),
            events_path=_path("events_path", "/events/{sid}"),
            send_path=_path("send_path", "/send/{sid}"),
            stop_path=_path("stop_path", "/stop/{sid}"),
            version_path=_path("version_path", "/version"),
        )

    def _probe_config_factory() -> tuple[str, tuple[int, ...], float] | None:
        """Return ``(host, ports, timeout_s)`` for auto-probe, or ``None``.

        Deployment topology is edition-config, not source
        (PROJECT-RULES §3.8.1): ``probe_host`` / ``probe_ports`` /
        ``probe_timeout_s`` live in ``[query_services.mb_pro]`` of
        ``internal_config.toml``. Missing / malformed pool config ⇒ ``None``
        (auto-probe silently disabled; connect falls back to the descriptor's
        single ``endpoint`` — backward compatible with a single-instance
        deployment).
        """
        fields = get_query_services().get("mb_pro")
        if not fields:
            return None
        host_raw = fields.get("probe_host")
        ports_raw = fields.get("probe_ports")
        if not isinstance(host_raw, str) or not host_raw:
            return None
        if not isinstance(ports_raw, (list, tuple)) or not ports_raw:
            return None
        ports: list[int] = []
        for p in ports_raw:
            if isinstance(p, bool):  # bool is-a int in Python; exclude explicitly
                continue
            if isinstance(p, int) and 1 <= p <= 65535:
                ports.append(p)
        if not ports:
            return None
        timeout_raw = fields.get("probe_timeout_s", 2.0)
        try:
            timeout = float(timeout_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            timeout = 2.0
        if timeout <= 0:
            timeout = 2.0
        return (host_raw, tuple(ports), timeout)

    # Greeting use case — built only when the chat container is ready (it
    # depends on the chat conversation repo + stream broadcaster + id
    # generator). Returns None if any dependency is missing so the controller
    # still constructs cleanly (just without greeting injection).
    greeting_use_case = _build_greeting_use_case(
        container=container,
        peek_manager=peek_session_manager,
    )

    # No mb_pro descriptor configured ⇒ the controller would be inert; still
    # build it so /state returns a clean "disconnected", but connect/version
    # raise "not configured" (handled by the factory returning None).
    return MbProSessionController(
        descriptor_factory=_descriptor_factory,
        probe_config_factory=_probe_config_factory,
        get_manager=get_session_manager,
        peek_manager=peek_session_manager,
        drop_manager=drop_session_manager,
        greeting_use_case=greeting_use_case,
    )


def _build_greeting_use_case(*, container: Any, peek_manager: Any) -> Any | None:
    """Build the greeting use case, or ``None`` if dependencies are missing.

    Best-effort: a missing chat dependency is logged once and treated as
    "feature disabled" rather than failing the whole bridge construction.
    """
    chat = getattr(container, "chat", None)
    if chat is None:
        return None
    conversations = getattr(chat, "conversations", None)
    broadcaster = getattr(chat, "chat_stream_broadcaster", None)
    ids = getattr(container, "ids", None) or getattr(chat, "ids", None)
    if conversations is None or broadcaster is None or ids is None:
        _log.info(
            "mb_pro.greeting_disabled_missing_deps",
            has_conversations=conversations is not None,
            has_broadcaster=broadcaster is not None,
            has_ids=ids is not None,
        )
        return None
    try:
        from qai.chat.application.use_cases.mb_pro_greeting import (
            PersistMbProGreetingUseCase,
        )
        # Infrastructure collaborators are constructed HERE at the composition
        # root (the layered contract forbids the application use case from
        # importing infrastructure). This bridge is already internal-gated and
        # is the legitimate place to wire concrete infra into the app-layer Port.
        from qai.chat.infrastructure.query_service.mapper import (
            QueryMappingContext,
        )
        from qai.chat.infrastructure.query_service.mappers.mb_pro_mapper import (
            MbProMapper,
        )
    except Exception:  # pragma: no cover - excluded on external
        return None

    class _MbProGreetingMapper:
        """Adapter satisfying ``GreetingMapperPort`` — wraps the infra mapper
        + per-stream context factory so the application use case stays free of
        any infrastructure import."""

        def __init__(self, id_gen: Any) -> None:
            self._ids = id_gen
            self._mapper = MbProMapper()

        def new_context(self) -> Any:
            return QueryMappingContext(ids=self._ids)

        def map_event(self, event: Any, ctx: Any) -> Any:
            return self._mapper.map_event(event, ctx)

    return PersistMbProGreetingUseCase(
        conversations=conversations,
        broadcaster=broadcaster,
        peek_manager=peek_manager,
        ids=ids,
        greeting_mapper=_MbProGreetingMapper(ids),
    )
