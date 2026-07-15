"""App Builder — import workflow routes (``/import`` family).

Dry-run / commit / rollback / candidates / scan-bins / auto-export. The
auto-export handler reaches the cross-context ``qai.model_builder`` export
pipeline through ``container.auto_export_bridge`` (AGENTS.md §3.2), so it
needs the raw ``container`` in addition to ``container.app_builder``.

Handler bodies are byte-for-byte identical to the pre-split module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, status

from ._dto import (
    AutoExportRequestBody,
    AutoExportResponseBody,
    CandidatesRequestBody,
    BinScanResponse,
    BinScanResultResponse,
    ImportCommitRequest,
    ImportCommitResponse,
    ImportDryRunRequest,
    ImportPlanResponse,
    ImportRollbackRequest,
    ImportRollbackResponse,
    ScanBinsRequestBody,
    _plan_item_payload_to_domain,
    _plan_to_dto,
)

from qai.app_builder.application.use_cases.import_workflow import (
    ImportCommitUseCase,
    ImportDryRunUseCase,
    ImportRollbackUseCase,
)
from qai.app_builder.domain.import_plan import CommitId, ImportPlan
from qai.platform.errors import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from apps.api.di import Container


def register(router: APIRouter, *, container: "Container") -> None:
    """Mount the import-workflow routes onto ``router``."""

    def _services() -> Any:
        return container.app_builder

    # ---- import workflow --------------------------------------------------

    @router.post("/import/dry-run", response_model=ImportPlanResponse)
    async def import_dry_run(
        body: ImportDryRunRequest,
    ) -> ImportPlanResponse:
        uc: ImportDryRunUseCase = _services().import_dry_run_use_case
        plan = await uc.execute(candidates=list(body.candidates))
        return _plan_to_dto(plan)

    @router.post(
        "/import/commit",
        response_model=ImportCommitResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def import_commit(body: ImportCommitRequest) -> ImportCommitResponse:
        try:
            domain_items = tuple(
                _plan_item_payload_to_domain(it) for it in body.items
            )
        except ValueError as exc:
            raise ValidationError(
                "app_builder.import_plan_invalid",
                str(exc),
                field_errors={"items": [str(exc)]},
            ) from exc
        plan = ImportPlan(items=domain_items)
        uc: ImportCommitUseCase = _services().import_commit_use_case
        commit_id: CommitId = await uc.execute(plan=plan)
        return ImportCommitResponse(commit_id=commit_id.value)

    @router.post("/import/rollback", response_model=ImportRollbackResponse)
    async def import_rollback(
        body: ImportRollbackRequest,
    ) -> ImportRollbackResponse:
        try:
            cid = CommitId(value=body.commit_id)
        except ValueError as exc:
            raise ValidationError(
                "app_builder.commit_id_invalid",
                str(exc),
                field_errors={"commit_id": [str(exc)]},
            ) from exc
        uc: ImportRollbackUseCase = _services().import_rollback_use_case
        await uc.execute(commit_id=cid)
        return ImportRollbackResponse(commit_id=cid.value, status="rolled_back")

    # ---- 4. import/candidates -----------------------------------------
    @router.post(
        "/import/candidates",
        response_model=ImportPlanResponse,
    )
    async def import_candidates(body: CandidatesRequestBody) -> ImportPlanResponse:
        uc: ImportDryRunUseCase = _services().import_dry_run_use_case
        plan = await uc.execute(body.candidates)
        return _plan_to_dto(plan)

    # ---- 5. import/scan-bins ------------------------------------------
    @router.post("/import/scan-bins", response_model=BinScanResponse)
    async def import_scan_bins(
        body: ScanBinsRequestBody | None = None,
    ) -> BinScanResponse:
        uc = _services().import_scan_bins_use_case
        if uc is None:
            raise HTTPException(status_code=503, detail="scan-bins use case not wired")
        model_workdir = body.model_workdir if body is not None else None
        results = await uc.execute(model_workdir=model_workdir)
        return BinScanResponse(
            results=[
                BinScanResultResponse(
                    path=r.path,
                    size_bytes=r.size_bytes,
                    suspected_model_id=r.suspected_model_id,
                    precision=r.precision,
                    label=r.label,
                    mtime=r.mtime,
                )
                for r in results
            ]
        )

    # ---- 6. import/auto-export ----------------------------------------
    @router.post(
        "/import/auto-export",
        response_model=AutoExportResponseBody,
        status_code=202,
    )
    async def import_auto_export(
        body: AutoExportRequestBody,
    ) -> AutoExportResponseBody:
        # The Pydantic ``Field(min_length=1, max_length=4096)`` on
        # ``source_path`` already enforces presence + sanity at parse
        # time. The actual export pipeline lives in the
        # ``qai.model_builder`` bounded context (cross-context
        # boundary per AGENTS.md §3.2); we reach it through the
        # ``container.auto_export_bridge`` composition adapter so
        # ``qai.app_builder`` never imports ``qai.model_builder``.
        bridge = getattr(container, "auto_export_bridge", None)
        if bridge is None:
            raise HTTPException(
                status_code=503,
                detail="auto-export bridge not wired",
            )

        try:
            job = await bridge.trigger_auto_export(
                model_workdir=body.source_path,
                model_name=body.model_name,
                precisions=tuple(body.precisions),
                default_precision=body.default_precision,
                category_override=body.category_override,
                display_name_override=body.display_name_override,
                input_kind_override=body.input_kind_override,
                output_kind_override=body.output_kind_override,
                pack_id_override=body.pack_id_override,
            )
        except FileNotFoundError as exc:
            raise NotFoundError(
                "app_builder.auto_export.source_not_found",
                "model_workdir",
                body.source_path,
                message=str(exc),
            ) from exc
        except (ValueError, PermissionError) as exc:
            raise ValidationError(
                "app_builder.auto_export.invalid_request", str(exc)
            ) from exc
        except Exception as exc:
            # Domain-error hierarchy lives in qai.model_builder.domain;
            # the bridge surfaces them via their string form here.
            cls_name = type(exc).__name__
            if cls_name in (
                "WorkspaceNotReadyError",
                "InvalidPrecisionError",
            ):
                raise ValidationError(
                    "app_builder.auto_export.invalid_request", str(exc)
                ) from exc
            if cls_name == "MissingContextBinError":
                raise ConflictError(
                    "app_builder.auto_export.missing_context_bin", str(exc)
                ) from exc
            if cls_name in (
                "MissingQaiAppBuilderError",
                "SmokeTestFailedError",
                "ManifestGenerationError",
            ):
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            raise

        return AutoExportResponseBody(
            accepted=True,
            note="export complete" if job.success else "export failed",
            success=job.success,
            pack_id=job.pack_id,
            display_name=job.display_name,
            source_workdir=job.source_workdir,
            output=job.output,
            errors=list(job.errors),
        )
