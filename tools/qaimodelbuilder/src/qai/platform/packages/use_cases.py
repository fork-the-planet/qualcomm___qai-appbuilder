"""Use case: list installed Python distributions.

Owns the business algorithm the legacy stub performed inline in the HTTP
layer (``interfaces/http/routes/versions.py`` ``get_installed``):

* deduplicate by distribution name (first occurrence wins);
* sort by lower-cased name (case-insensitive, ascending);
* truncate to the first ``_MAX_PACKAGES`` entries.

The raw enumeration is delegated to an :class:`InstalledPackagesPort`
adapter so this layer stays free of :mod:`importlib.metadata`.
"""

from __future__ import annotations

from qai.platform.packages.ports import InstalledPackagesPort
from qai.platform.packages.types import InstalledPackage

# Legacy stub cap: at most 200 packages are returned to the version panel.
_MAX_PACKAGES: int = 200


class ListInstalledPackagesUseCase:
    """Orchestrates enumeration → dedup → sort → truncate."""

    def __init__(self, *, source: InstalledPackagesPort) -> None:
        self._source = source

    def execute(self) -> list[InstalledPackage]:
        packages: list[InstalledPackage] = []
        seen: set[str] = set()
        for package in self._source.enumerate():
            if package.name in seen:
                continue
            seen.add(package.name)
            packages.append(package)
        packages.sort(key=lambda p: p.name.lower())
        return packages[:_MAX_PACKAGES]
