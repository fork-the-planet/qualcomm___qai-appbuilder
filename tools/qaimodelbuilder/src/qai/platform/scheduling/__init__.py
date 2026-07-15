"""Public API for ``qai.platform.scheduling``.

Exports :class:`BackgroundTaskManager`, a platform-neutral, edition-agnostic
periodic task scheduler (run-once-on-start + repeat-every-interval) driven by
the application lifespan. See ``background_tasks.py`` for details.
"""

from __future__ import annotations

from .background_tasks import BackgroundTaskManager, TaskFunc

__all__ = [
    "BackgroundTaskManager",
    "TaskFunc",
]
