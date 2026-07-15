"""Value objects for the platform installed-packages shared kernel sub-module.

This module is part of the shared kernel and may be imported by any BC /
interface that needs to enumerate installed Python distributions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    """Immutable record describing a single installed Python distribution."""

    name: str
    version: str
    location: str = ""
