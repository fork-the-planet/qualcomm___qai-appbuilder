"""qai.platform.packages — Cross-BC platform sub-module for enumerating
installed Python distributions.

This shared-kernel module provides a reusable abstraction over installed
package enumeration so the HTTP layer no longer reaches for
:mod:`importlib.metadata` and embeds dedup/sort/truncate logic inline.

Public API:
    - :class:`InstalledPackage` — immutable record for one distribution
    - :class:`InstalledPackagesPort` — Protocol for the enumeration source
    - :class:`ImportlibInstalledPackages` — importlib.metadata adapter
    - :class:`ListInstalledPackagesUseCase` — dedup/sort/truncate orchestration
"""

from __future__ import annotations

from qai.platform.packages.importlib_source import ImportlibInstalledPackages
from qai.platform.packages.ports import InstalledPackagesPort
from qai.platform.packages.types import InstalledPackage
from qai.platform.packages.use_cases import ListInstalledPackagesUseCase

__all__ = [
    "ImportlibInstalledPackages",
    "InstalledPackage",
    "InstalledPackagesPort",
    "ListInstalledPackagesUseCase",
]
