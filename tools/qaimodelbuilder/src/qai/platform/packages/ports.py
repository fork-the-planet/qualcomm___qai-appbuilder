"""Port (Protocol) for enumerating installed Python distributions.

Consumers depend on :class:`InstalledPackagesPort` rather than reaching
for :mod:`importlib.metadata` directly so the underlying enumeration
strategy (importlib, a pip subprocess, a fake in tests, …) can be
swapped without touching business logic or the HTTP layer.
"""

from __future__ import annotations

from typing import Protocol

from qai.platform.packages.types import InstalledPackage


class InstalledPackagesPort(Protocol):
    """Abstract source of installed Python distributions."""

    def enumerate(self) -> list[InstalledPackage]:
        """Return every installed distribution as a raw (unsorted) list.

        Implementations must NOT deduplicate, sort, or truncate — those
        are business concerns owned by the use case. They simply surface
        whatever the underlying source reports, one entry per distribution
        as discovered.
        """
        ...
