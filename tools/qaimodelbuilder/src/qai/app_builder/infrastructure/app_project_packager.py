"""Filesystem-backed app-project packager (plan §2.4 / §5.6 / §10.4).

Builds a distributable ``.zip`` of a generated standalone app project —
the app's own code (backend / frontend / launch scripts / ``app.yaml``)
plus, optionally, the minimal model + weight set each bundled model needs
to run on a target machine — and drops it under the user workspace at
``<workspace>/app_builder_packages/<app_id>-<YYYYMMDD-HHMMSS>.zip``.

Layering (import-linter ``layered-app_builder``): this module lives in
the infrastructure layer and imports domain freely. It deliberately does
NOT import the ``AppProjectPackagerPort`` protocol (added to
``application/ports.py`` by the DI-wiring step) — the port is a
structural :class:`typing.Protocol`, so :class:`FileSystemAppProjectPackager`
satisfies it by shape (matching method name / signature) without an
import, keeping infrastructure free of an application-layer dependency
for a pure duck-typed contract. The DI container passes an instance of
this class wherever the port is expected.

Structural contract satisfied (``AppProjectPackagerPort``)::

    def package(
        self, definition: AppProjectDefinition
    ) -> AsyncIterator[PackageProgress]

Design (progressive, cancel-safe, path-safe)
--------------------------------------------
* :meth:`package` is an **async generator** yielding :class:`PackageProgress`
  snapshots so the SSE route can stream live phase / percent updates while
  a large weight copy runs. The final snapshot has ``is_complete=True``
  carrying ``zip_path`` + ``size_bytes``.
* The zip is built into a temp file first, then atomically moved into the
  ``app_builder_packages`` dir — a crash / cancel mid-build never leaves a
  half-written ``<app_id>-<ts>.zip`` for the UI to offer as "done".
* Path safety (plan §5.8): the app dir MUST resolve under ``apps_root``
  and every member added to the zip MUST resolve under the app dir (no
  symlink escape). Model weight copy paths MUST resolve under
  ``repo_root/models`` or the pack root.
* ``${APP_ROOT}`` placeholders in a model ref's ``model_dir`` / ``pack_dir``
  are expanded against the injected ``repo_root`` (see :meth:`_expand`).
"""

from __future__ import annotations

import asyncio
import json
import os
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qai.app_builder.domain.app_project import (
    AppProjectDefinition,
    AppProjectModelRef,
    AppProjectPackageFailedError,
)
from qai.platform.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "FileSystemAppProjectPackager",
    "PackageProgress",
]

# Placeholder token the ``app.yaml`` model refs use for the repo root.
_APP_ROOT_TOKEN = "${APP_ROOT}"  # noqa: S105 - path placeholder token, not a secret

# Top-level app entries always packaged when present (files + dirs). The
# member paths in the zip are rooted at the app id's parent (i.e. the zip
# stores ``backend/main.py`` etc., not ``<app_id>/backend/main.py``).
_APP_INCLUDE_FILES = (
    "README.md",
    "run.bat",
    "run.ps1",
    "run.sh",
    "requirements.txt",
    "app.yaml",
)
_APP_INCLUDE_DIRS = ("backend", "frontend")

# Directory names excluded ANYWHERE in the app tree (venvs / caches / the
# package output dir itself / user uploads / logs). Matched case-insensitively
# on the directory *name* so ``.venv`` deep in ``backend/`` is skipped too.
_EXCLUDE_DIR_NAMES = frozenset(
    {
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
        "package",  # the app's own package output dir
        "uploads",  # user uploads — never redistribute
        "node_modules",
    }
)

# File suffixes excluded anywhere.
_EXCLUDE_SUFFIXES = frozenset({".pyc", ".pyo", ".pyd"})

# ``logs/`` is excluded only for its large ``*.log`` bodies; the dir itself
# and small non-log files may pass, but in practice we skip the whole dir.
_EXCLUDE_LOG_DIR = "logs"

# Pack manifest / doc files copied (per §10.4) from the expanded pack dir.
_PACK_INCLUDE_FILES = (
    "manifest.json",
    "weights.json",
    "SKILL.md",
    "runner.py",
    "requirements.txt",
)
_PACK_INCLUDE_DIRS = ("assets", "provenance")


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageProgress:
    """One progress snapshot yielded while packaging an app project.

    ``phase`` is a coarse machine label (``"collecting"`` / ``"copying_app"``
    / ``"copying_models"`` / ``"writing_zip"`` / ``"done"``); ``percent`` is a
    ``0..100`` float estimate; ``message`` is a short human line. The terminal
    snapshot sets ``is_complete=True`` and carries the final ``zip_path`` +
    ``size_bytes`` (both ``None`` on every non-terminal snapshot).
    """

    phase: str
    percent: float
    message: str
    zip_path: str | None = None
    size_bytes: int | None = None
    is_complete: bool = False


class FileSystemAppProjectPackager:
    """Package a standalone app project into a workspace-rooted ``.zip``.

    ``repo_root`` anchors ``${APP_ROOT}`` expansion + the model / pack roots
    (``repo_root/models``, ``repo_root/factory/app_builder/models``).
    ``workspace_root`` is the user workspace the final zip lands under
    (``<workspace>/app_builder_packages/``). ``apps_root`` is the
    ``data/app_builder`` dir every app must resolve under (path-safety
    containment). ``clock`` returns the timestamp used in the zip file name
    (injectable for deterministic tests; defaults to ``datetime.now``).
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        workspace_root: Path,
        apps_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo_root = Path(repo_root)
        self._workspace_root = Path(workspace_root)
        self._apps_root = Path(apps_root)
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def model_root(self) -> Path:
        """``APP_BUILDER_MODEL_ROOT`` — real weight tree (``repo_root/models``)."""
        return self._repo_root / "models"

    @property
    def pack_root(self) -> Path:
        """``APP_BUILDER_PACK_ROOT`` — pack manifests / assets tree."""
        return self._repo_root / "factory" / "app_builder" / "models"

    # ── public port method ───────────────────────────────────────────────

    async def package(  # noqa: PLR0915 - cohesive progressive generator: sequential build phases with interleaved progress yields
        self, definition: AppProjectDefinition
    ) -> AsyncIterator[PackageProgress]:
        """Build the app package, yielding progress until ``is_complete``.

        Raises :class:`AppProjectPackageFailedError` (``app_builder.package_failed``)
        on a path-escape / IO failure BEFORE the first yield; a missing model
        / pack path mid-build is recorded as a warning in the manifest and
        skipped (never crashes the whole package).
        """
        app_id = definition.id.value
        app_dir = self._resolve_app_dir(definition)

        # ── collecting: plan the member set + estimate size ───────────────
        yield PackageProgress(
            phase="collecting",
            percent=0.0,
            message=f"collecting files for {app_id!r}",
        )
        app_members = self._collect_app_members(app_dir)
        warnings: list[str] = []
        model_plan: list[tuple[AppProjectModelRef, list[tuple[Path, str]]]] = []
        if definition.package_include_models:
            for ref in definition.models:
                members = self._collect_model_members(ref, warnings)
                model_plan.append((ref, members))

        app_bytes = _sum_size(m[0] for m in app_members)
        model_bytes = _sum_size(
            src for _, members in model_plan for src, _ in members
        )
        total_bytes = max(app_bytes + model_bytes, 1)
        copied = 0

        # ── build the zip into a temp file ────────────────────────────────
        out_dir = self._workspace_root / "app_builder_packages"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AppProjectPackageFailedError(
                message=f"cannot create package output dir {out_dir}: {exc}",
            ) from exc

        stamp = self._clock().strftime("%Y%m%d-%H%M%S")
        final_path = out_dir / f"{app_id}-{stamp}.zip"
        tmp_path = out_dir / f".{app_id}-{stamp}.zip.part"

        model_ids = [ref.id for ref, _ in model_plan]

        try:
            with zipfile.ZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                # App files. Each ``zf.write`` is BLOCKING disk+deflate IO; we
                # run it via ``asyncio.to_thread`` and ``await`` so the event
                # loop stays free and the StreamingResponse can actually FLUSH
                # each progress frame to the browser as we go (otherwise the
                # whole multi-hundred-MB copy blocks the loop and every frame
                # arrives at once at the very end → the bar sat at 0%). We also
                # yield progress periodically DURING the copy (per file for big
                # model weights, throttled for many small app files) so the
                # percent advances smoothly instead of jumping 0 → 92.
                yield PackageProgress(
                    phase="copying_app",
                    percent=_pct(copied, total_bytes) * 0.9,
                    message="packaging app files",
                )
                _since_yield = 0
                for src, arcname in app_members:
                    await asyncio.to_thread(zf.write, src, arcname)
                    copied += _safe_size(src)
                    _since_yield += 1
                    # App files are usually small + numerous; yield every few
                    # so the bar moves without flooding the SSE stream.
                    if _since_yield >= 8:
                        _since_yield = 0
                        yield PackageProgress(
                            phase="copying_app",
                            percent=_pct(copied, total_bytes) * 0.9,
                            message="packaging app files",
                        )
                        await asyncio.sleep(0)  # let the response flush

                # Model weights + pack manifests. Weight files are large, so
                # yield after EACH file for a responsive bar.
                if model_plan:
                    yield PackageProgress(
                        phase="copying_models",
                        percent=_pct(copied, total_bytes) * 0.9,
                        message=f"packaging {len(model_plan)} model(s)",
                    )
                    await asyncio.sleep(0)
                    for ref, members in model_plan:
                        for src, arcname in members:
                            await asyncio.to_thread(zf.write, src, arcname)
                            copied += _safe_size(src)
                            yield PackageProgress(
                                phase="copying_models",
                                percent=_pct(copied, total_bytes) * 0.9,
                                message=f"packaging model {ref.id!r}",
                            )
                            await asyncio.sleep(0)  # let the response flush
                        yield PackageProgress(
                            phase="copying_models",
                            percent=_pct(copied, total_bytes) * 0.9,
                            message=f"packaged model {ref.id!r}",
                        )

                # Manifest + running doc (small, computed last).
                yield PackageProgress(
                    phase="writing_zip",
                    percent=92.0,
                    message="writing package manifest",
                )
                manifest = _build_manifest(
                    app_id=app_id,
                    definition=definition,
                    model_ids=model_ids,
                    total_size_bytes=app_bytes + model_bytes,
                    packaged_at=self._clock(),
                    warnings=warnings,
                )
                zf.writestr(
                    "package_manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
                zf.writestr("RUNNING.md", _RUNNING_MD)
        except AppProjectPackageFailedError:
            _unlink_quiet(tmp_path)
            raise
        except OSError as exc:
            _unlink_quiet(tmp_path)
            raise AppProjectPackageFailedError(
                message=f"failed to write package for {app_id!r}: {exc}",
            ) from exc

        # ── atomic move into place ─────────────────────────────────────────
        try:
            if final_path.exists():
                final_path.unlink()
            os.replace(tmp_path, final_path)
        except OSError as exc:
            _unlink_quiet(tmp_path)
            raise AppProjectPackageFailedError(
                message=f"failed to finalize package for {app_id!r}: {exc}",
            ) from exc

        size_bytes = _safe_size(final_path)
        yield PackageProgress(
            phase="done",
            percent=100.0,
            message=f"packaged {app_id!r} ({size_bytes} bytes)",
            zip_path=str(final_path),
            size_bytes=size_bytes,
            is_complete=True,
        )

    # ── path safety ────────────────────────────────────────────────────

    def _resolve_app_dir(self, definition: AppProjectDefinition) -> Path:
        """Resolve + containment-check the app dir under ``apps_root``.

        Uses ``definition.path`` (the repository-filled absolute app dir).
        Raises :class:`AppProjectPackageFailedError` when the resolved dir
        escapes ``apps_root`` or does not exist.
        """
        try:
            app_dir = Path(definition.path).resolve()
            root = self._apps_root.resolve()
        except OSError as exc:
            raise AppProjectPackageFailedError(
                message=f"cannot resolve app dir for {definition.id.value!r}: {exc}",
            ) from exc
        if app_dir != root and root not in app_dir.parents:
            raise AppProjectPackageFailedError(
                message=f"app dir {app_dir} escapes apps root {root}",
            )
        if not app_dir.is_dir():
            raise AppProjectPackageFailedError(
                message=f"app dir {app_dir} does not exist",
            )
        return app_dir

    def _expand(self, raw: str) -> Path:
        """Expand ``${APP_ROOT}`` in ``raw`` against ``repo_root`` + resolve."""
        replaced = raw.replace(_APP_ROOT_TOKEN, str(self._repo_root))
        return Path(replaced).resolve()

    @staticmethod
    def _is_under(child: Path, parent: Path) -> bool:
        """Whether ``child`` resolves at / under ``parent`` (both resolved)."""
        try:
            child_r = child.resolve()
            parent_r = parent.resolve()
        except OSError:
            return False
        return child_r == parent_r or parent_r in child_r.parents

    # ── member collection ────────────────────────────────────────────────

    def _collect_app_members(self, app_dir: Path) -> list[tuple[Path, str]]:
        """Return ``(src_path, arcname)`` pairs for the app's own files.

        Applies the exclude whitelist (venvs / caches / package / uploads /
        logs) and refuses to follow a symlink that escapes ``app_dir`` (plan
        §5.8). Arcnames are POSIX-relative to ``app_dir``.
        """
        members: list[tuple[Path, str]] = []

        for name in _APP_INCLUDE_FILES:
            src = app_dir / name
            if src.is_file() and self._is_under(src, app_dir):
                members.append((src, name))

        for dirname in _APP_INCLUDE_DIRS:
            base = app_dir / dirname
            if not base.is_dir():
                continue
            members.extend(self._walk_dir(base, app_dir))

        return members

    def _walk_dir(
        self, base: Path, app_dir: Path
    ) -> list[tuple[Path, str]]:
        """Walk ``base`` (a dir under ``app_dir``) applying the exclude rules."""
        out: list[tuple[Path, str]] = []
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            # Prune excluded directories in-place so os.walk never descends.
            dirs[:] = [
                d for d in dirs if d.casefold() not in _EXCLUDE_DIR_NAMES
            ]
            # Skip anything under a logs/ dir (large rotating logs).
            rel_parts = {p.casefold() for p in root_path.relative_to(app_dir).parts}
            if _EXCLUDE_LOG_DIR in rel_parts:
                continue
            for fname in files:
                if Path(fname).suffix.casefold() in _EXCLUDE_SUFFIXES:
                    continue
                src = root_path / fname
                # Symlink-escape guard: a member must resolve under app_dir.
                if src.is_symlink() and not self._is_under(src, app_dir):
                    logger.warning(
                        "app_project_packager: skip escaping symlink %s", src
                    )
                    continue
                if not src.is_file():
                    continue
                arcname = src.relative_to(app_dir).as_posix()
                out.append((src, arcname))
        return out

    def _collect_model_members(
        self, ref: AppProjectModelRef, warnings: list[str]
    ) -> list[tuple[Path, str]]:
        """Return ``(src, arcname)`` pairs for one model ref's weights + pack.

        Weights land under ``models/<id>/`` in the zip; pack manifests /
        assets under ``pack/<id>/``. Missing paths are recorded in
        ``warnings`` and skipped (never raised) so one absent model cannot
        abort the whole package (plan §10.4).
        """
        out: list[tuple[Path, str]] = []
        out.extend(self._collect_model_weights(ref, warnings))
        out.extend(self._collect_model_pack(ref, warnings))
        return out

    def _collect_model_weights(
        self, ref: AppProjectModelRef, warnings: list[str]
    ) -> list[tuple[Path, str]]:
        """Weight files for ``ref`` under ``models/<id>/`` (plan §10.4)."""
        out: list[tuple[Path, str]] = []
        # Weights: expand model_dir (or fall back to repo_root/models/<id>).
        if ref.model_dir:
            model_dir = self._expand(ref.model_dir)
        else:
            model_dir = (self.model_root / ref.id).resolve()
        if not self._is_under(model_dir, self.model_root):
            warnings.append(
                f"model {ref.id!r}: model_dir {model_dir} outside models root; skipped"
            )
        elif not model_dir.is_dir():
            warnings.append(
                f"model {ref.id!r}: weights dir {model_dir} missing; skipped"
            )
        else:
            for src in _iter_files(model_dir):
                rel = src.relative_to(model_dir).as_posix()
                out.append((src, f"models/{ref.id}/{rel}"))
        return out

    def _collect_model_pack(
        self, ref: AppProjectModelRef, warnings: list[str]
    ) -> list[tuple[Path, str]]:
        """Pack manifests / assets for ``ref`` under ``pack/<id>/`` (plan §10.4)."""
        out: list[tuple[Path, str]] = []
        # Pack: expand pack_dir (or fall back to pack_root/<id>).
        if ref.pack_dir:
            pack_dir = self._expand(ref.pack_dir)
        else:
            pack_dir = (self.pack_root / ref.id).resolve()
        if not self._is_under(pack_dir, self.pack_root):
            warnings.append(
                f"model {ref.id!r}: pack_dir {pack_dir} outside pack root; skipped"
            )
        elif not pack_dir.is_dir():
            warnings.append(
                f"model {ref.id!r}: pack dir {pack_dir} missing; skipped"
            )
        else:
            for name in _PACK_INCLUDE_FILES:
                src = pack_dir / name
                if src.is_file():
                    out.append((src, f"pack/{ref.id}/{name}"))
            for dirname in _PACK_INCLUDE_DIRS:
                sub = pack_dir / dirname
                if sub.is_dir():
                    for src in _iter_files(sub):
                        rel = src.relative_to(pack_dir).as_posix()
                        out.append((src, f"pack/{ref.id}/{rel}"))
        return out


# ---------------------------------------------------------------------------
# Module-level helpers (pure)
# ---------------------------------------------------------------------------
def _iter_files(base: Path) -> list[Path]:
    """Return every regular file under ``base`` (recursive), caches excluded.

    Symlink-escape guard (plan §5.8): if a file is a symlink whose target
    resolves outside ``base``, it is skipped + logged. ``os.walk`` already
    does not follow symlinked *directories* (``followlinks=False`` default),
    but symlinked *files* still need this explicit check so a malicious /
    misconfigured model dir cannot leak arbitrary files into the package.
    """
    out: list[Path] = []
    try:
        base_real = base.resolve()
    except OSError:
        return out
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d.casefold() not in _EXCLUDE_DIR_NAMES]
        for fname in files:
            if Path(fname).suffix.casefold() in _EXCLUDE_SUFFIXES:
                continue
            src = Path(root) / fname
            if src.is_symlink():
                try:
                    tgt = src.resolve(strict=True)
                except OSError:
                    logger.warning(
                        "app_project_packager.skip_broken_symlink",
                        path=str(src),
                    )
                    continue
                try:
                    tgt.relative_to(base_real)
                except ValueError:
                    logger.warning(
                        "app_project_packager.skip_escaping_symlink",
                        path=str(src),
                    )
                    continue
            if src.is_file():
                out.append(src)
    return out


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sum_size(paths) -> int:
    return sum(_safe_size(p) for p in paths)


def _pct(copied: int, total: int) -> float:
    return min(100.0, max(0.0, (copied / total) * 100.0)) if total else 0.0


def _unlink_quiet(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _build_manifest(
    *,
    app_id: str,
    definition: AppProjectDefinition,
    model_ids: list[str],
    total_size_bytes: int,
    packaged_at: datetime,
    warnings: list[str],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "app_id": app_id,
        "name": definition.name,
        "description": definition.description,
        "packaged_at": packaged_at.isoformat(),
        "models": list(model_ids),
        "include_models": definition.package_include_models,
        "include_outputs": definition.package_include_outputs,
        "total_size_bytes": total_size_bytes,
        "target_platform": (
            "Windows on Snapdragon (WoS) ARM64 with a QAI ModelBuilder "
            "Python environment. Not a fully self-contained offline package."
        ),
        "warnings": list(warnings),
    }


_RUNNING_MD = """\
# Running this packaged app

This ZIP contains the app's source (backend + frontend), its launch
scripts, and — when bundled — the minimal model weight / pack files each
model needs.

## Important: this is NOT a fully offline package

The target machine MUST already have a working **QAI ModelBuilder Python
environment** (the `qai_appbuilder` runtime + QAIRT SDK) available. This
package does not ship a Python interpreter or the QNN runtime, so it will
not run on an arbitrary Windows machine without that environment.

## Steps

1. Unzip this package on a Windows on Snapdragon (WoS) ARM64 machine that
   has the QAI ModelBuilder Python environment installed.
2. Open a terminal in the unzipped directory.
3. Run `run.bat` (or `run.ps1`).
4. Open the printed local URL in your browser.

Bundled model weights are under `models/<model_id>/`; the corresponding
pack manifests / assets are under `pack/<model_id>/`.
"""
