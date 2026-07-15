"""importlib.metadata-backed adapter for :class:`InstalledPackagesPort`.

Isolates the only infrastructure dependency (``importlib.metadata``) at
the edge so the use case / HTTP layer never reaches for it directly.
"""

from __future__ import annotations

from qai.platform.packages.types import InstalledPackage


class ImportlibInstalledPackages:
    """Adapter: enumerates distributions via :mod:`importlib.metadata`.

    Surfaces one :class:`InstalledPackage` per discovered distribution
    without deduplication / sorting / truncation (those belong to the
    use case). The ``location`` mirrors the legacy stub: the parent of
    the distribution's private ``_path`` when available, else ``""``.
    """

    def enumerate(self) -> list[InstalledPackage]:
        from importlib.metadata import distributions

        packages: list[InstalledPackage] = []
        for dist in distributions():
            name = dist.metadata["Name"] or ""
            packages.append(
                InstalledPackage(
                    name=name,
                    version=dist.metadata["Version"] or "0.0.0",
                    location=str(dist._path.parent) if hasattr(dist, "_path") else "",
                )
            )
        return packages
