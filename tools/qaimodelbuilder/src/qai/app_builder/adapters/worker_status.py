"""Worker-status adapters (PR-045 + PR-301).

Two adapters live here:

* :class:`StaticWorkerStatusAdapter` — PR-045 inline-runner stub that
  returns a fixed snapshot. Kept verbatim because tests and DI
  fallbacks still rely on it (and the v2.7 §3.1 field-name lock means
  we don't rename the class).

* :class:`StickyWorkerStatusAdapter` — PR-301 real adapter that reads
  state from a live :class:`StickyWorkerHost` instance and projects it
  onto the SSOT :class:`WorkerPoolStatus` shape (loaded_models[],
  alive, multimodel, active_model_id, state).

Both adapters satisfy the same
:class:`qai.app_builder.application.ports.WorkerStatusPort` Protocol so
DI can swap between them based on whether sticky-worker is enabled at
spawn time.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from qai.app_builder.application.ports import (
    LoadedModelInfo,
    WorkerPoolStatus,
)

if TYPE_CHECKING:  # pragma: no cover
    from qai.app_builder.infrastructure.sticky_worker import StickyWorkerHost

__all__ = [
    "StaticWorkerStatusAdapter",
    "StickyWorkerStatusAdapter",
]


class StaticWorkerStatusAdapter:
    """Return a fixed :class:`WorkerPoolStatus`.

    Constructor knobs:

    * ``total_workers`` (default ``1``);
    * ``busy_workers`` (default ``0``);
    * ``queued_runs`` (default ``0``).

    The defaults model the inline-runner case used by the rest of
    PR-045's wiring; tests can pass concrete numbers to drive the
    underlying use case through both happy and saturated branches.
    """

    __slots__ = ("_total", "_busy", "_queued")

    def __init__(
        self,
        *,
        total_workers: int = 1,
        busy_workers: int = 0,
        queued_runs: int = 0,
    ) -> None:
        self._total = int(total_workers)
        self._busy = int(busy_workers)
        self._queued = int(queued_runs)

    async def status(self) -> WorkerPoolStatus:
        return WorkerPoolStatus(
            total_workers=self._total,
            busy_workers=self._busy,
            queued_runs=self._queued,
        )


class StickyWorkerStatusAdapter:
    """Live adapter wrapping :class:`StickyWorkerHost`.

    Projects the host's runtime state onto the new SSOT
    :class:`WorkerPoolStatus` fields (``alive``, ``state``,
    ``multimodel``, ``active_model_id``, ``loaded_models``) while
    keeping the legacy three numeric fields intact:

    * ``total_workers`` — always ``1`` for the single-process sticky
      worker (legacy parity); a multi-worker pool is intentionally
      outside the supported deployment shape.
    * ``busy_workers`` — ``1`` iff the host is in ``"busy"`` state.
    * ``queued_runs`` — ``0``; the sticky-worker host serialises runs
      on its single asyncio task and does not expose a queue depth,
      so the field is a fixed informational value.
    """

    __slots__ = ("_host",)

    def __init__(self, host: "StickyWorkerHost") -> None:
        if host is None:  # pragma: no cover — defensive
            raise ValueError("host must be a StickyWorkerHost instance")
        self._host = host

    async def status(self) -> WorkerPoolStatus:
        host = self._host
        snapshot = host.loaded_models_snapshot()
        now = time.time()
        loaded = tuple(
            LoadedModelInfo(
                model_id=entry.model_id,
                variant_id=entry.variant_id,
                last_used_at=entry.last_used_at,
                age_seconds=max(0.0, now - entry.last_used_at),
                state=entry.state,
            )
            for entry in snapshot
        )
        alive = host.alive
        state = host.state
        # The cross-field invariant on WorkerPoolStatus requires that
        # ``alive=False`` paired with a non-empty loaded_models tuple is
        # rejected. The host should already clear loaded_models on
        # _mark_dead, but we guard anyway to keep the route layer safe.
        if not alive and loaded:
            loaded = ()
        busy = 1 if state == "busy" else 0
        return WorkerPoolStatus(
            total_workers=1,
            busy_workers=busy,
            queued_runs=0,
            alive=alive,
            state=state,  # type: ignore[arg-type]
            active_model_id=host.active_model_id,
            multimodel=host.multimodel,
            loaded_models=loaded,
        )
