"""Live ``.bin`` I/O contract extraction + zero-tensor smoke test.

Direct port of
``features/model-builder/scripts/qai_pack_export.py:_extract_and_smoke_test_contract``.

Why this exists
---------------

The single most important quality gate in the export pipeline: a
Pack that fails this step is broken and we refuse to ship it. By
contrast a Pack that passes is *guaranteed* to load and infer in
AppBuilder (the runtime path uses the same ``qai_appbuilder`` API).

Failure modes surfaced here (any one is a hard abort):

* ``.bin`` unreadable / wrong runtime version → ``QnnContext.load``
  raises;
* native getter inconsistency (model has 2 inputs but reports 1
  dtype);
* zero-tensor inference itself crashes (op compatibility / runtime
  mismatch).

When the host environment lacks the ``qai_appbuilder`` runtime
(common on dev boxes that author Packs from remote ``.bin`` files),
we raise :class:`MissingQaiAppBuilderError` rather than silently
skipping validation — same hard-abort policy as the legacy script.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from qai.model_builder.domain import (
    MissingQaiAppBuilderError,
    SmokeTestFailedError,
)

__all__ = [
    "extract_and_smoke_test_contract",
]


def extract_and_smoke_test_contract(
    context_bin: Path,
    *,
    shared_dir: Path | None = None,
) -> dict[str, Any]:
    """Load ``context_bin``, query its native I/O contract, run zeros once.

    The returned dict goes into ``manifest.io_contract`` and becomes
    the SSOT for runtime shape / dtype.

    The ``shared_dir`` argument lets DI override where to find
    ``qnn_helper`` + ``io_validator`` (the App Builder shared runner
    helpers). When ``None`` we fall back to the canonical layout
    inherited from the legacy script:
    ``<repo>/features/app-builder/shared/`` — but since this adapter
    runs inside the new architecture, the recommended deployment
    bundles those helpers under ``data/runtime/app_builder_shared/``
    or similar; DI passes the resolved path. When neither is
    available the import simply fails through the
    :class:`MissingQaiAppBuilderError` path.
    """
    # Late import so the export pipeline does not hard-require
    # ``qai_appbuilder`` to be installed on the host that runs the
    # API server. The import error surfaces clearly via our typed
    # domain error rather than as a generic ``ModuleNotFoundError``
    # at module top.
    if shared_dir is not None and shared_dir.is_dir():
        shared_str = str(shared_dir)
        if shared_str not in sys.path:
            sys.path.insert(0, shared_str)

    try:
        from qnn_helper import QnnContext  # type: ignore[import-not-found]
        import io_validator as _iv  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingQaiAppBuilderError(
            "qai_appbuilder / shared modules unavailable on this host; "
            "cannot validate .bin. Run the API process inside an "
            "environment where the same qai_appbuilder is installed "
            "that App Builder would use at runtime. "
            f"Original import error: {exc}"
        ) from exc

    try:
        ctx = QnnContext.load(context_bin, runtime="Htp", log_level=1)
    except Exception as exc:  # noqa: BLE001 — qai_appbuilder may raise anything
        raise SmokeTestFailedError(
            f"failed to load context binary via qai_appbuilder: {exc} "
            f"(context_bin={context_bin}). This usually means the .bin "
            "was built against a different QAIRT runtime version, the "
            "file is corrupted, or the target backend (HTP) is not "
            "available on this host."
        ) from exc

    try:
        # The QnnContext wrapper may proxy native getters via its inner
        # ``_ctx`` attribute; otherwise call directly on the wrapper.
        native = getattr(ctx, "_ctx", None) or ctx

        contract = _iv.extract_io_contract(native, validated_at_export=False)

        # Smoke test: invoke once with zero tensors.
        try:
            zeros = _iv.zero_inputs_for_contract(contract)
            _ = ctx.run(zeros)
        except Exception as exc:  # noqa: BLE001
            raise SmokeTestFailedError(
                f"zero-tensor smoke test failed during export: {exc} "
                f"(context_bin={context_bin}). This indicates the .bin "
                "loads but cannot be invoked. The Pack was not produced. "
                "Re-run the conversion pipeline."
            ) from exc

        contract["validated_at_export"] = True
        return contract
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001 — best-effort close
            pass
