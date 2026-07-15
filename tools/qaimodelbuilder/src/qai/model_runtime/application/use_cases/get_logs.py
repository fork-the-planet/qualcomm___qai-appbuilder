"""``GetLogsUseCase`` — return recent daemon log lines."""

from __future__ import annotations

from qai.model_runtime.application.ports import InferenceServicePort


class GetLogsUseCase:
    """Return recent log lines from the inference daemon."""

    def __init__(self, *, service: InferenceServicePort) -> None:
        self._service = service

    async def execute(self) -> list[str]:
        return await self._service.get_logs()


__all__ = ["GetLogsUseCase"]
