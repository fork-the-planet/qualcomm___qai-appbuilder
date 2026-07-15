"""``ClearLogsUseCase`` — clear the daemon log buffer."""

from __future__ import annotations

from qai.model_runtime.application.ports import InferenceServicePort


class ClearLogsUseCase:
    """Clear the retained log buffer of the inference daemon.

    Returns the post-clear write sequence number (V1 ``skip_from``) so the
    frontend can resume streaming without replaying cleared history.
    """

    def __init__(self, *, service: InferenceServicePort) -> None:
        self._service = service

    async def execute(self) -> dict[str, object]:
        skip_from = await self._service.clear_logs()
        return {"status": "cleared", "skip_from": skip_from}


__all__ = ["ClearLogsUseCase"]
