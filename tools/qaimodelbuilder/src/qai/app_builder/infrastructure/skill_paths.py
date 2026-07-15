"""Filesystem locator for App Builder SKILL.md file paths.

Companion to :class:`qai.app_builder.application.use_cases.skill_and_schema.FilesystemSkillFileLoader`
(which reads SKILL *bodies*); this adapter resolves the *paths* of the
SKILL files the chat system prompt should inline for an App Builder
session — the top-level guide plus the currently selected Pack's SKILL.

V1 parity (``backend/app_builder/skill_resolver.resolve_skill_files``):

* the top-level ``<pack_root>/../SKILL.md`` (V2 ships it at
  ``factory/app_builder/SKILL.md``; ``pack_root`` is
  ``factory/app_builder/models``, so it is ``pack_root.parent / "SKILL.md"``),
  injected unconditionally when the file exists;
* the selected Pack's SKILL file (``<pack_root>/<model_id>/<skill_file>``)
  injected only when ``manifest.skill.enabled`` and the file exists.

The locator returns **absolute, existing** path strings so the chat
:class:`RichSystemPromptBuilder._build_app_builder_prompt` can ``open()``
them directly. Missing files are skipped (never raised) so a half-installed
Pack never breaks the chat prompt.

Implements the structural
:class:`qai.app_builder.application.use_cases.skill_and_schema.SkillPathLocator`
protocol; wired by ``apps/api/_app_builder_di.py``.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["FilesystemSkillPathLocator"]


class FilesystemSkillPathLocator:
    """Resolve SKILL.md file paths for the App Builder chat prompt.

    Bounded to ``pack_root`` for the per-model lookup (relative paths
    cannot escape via ``..``). The top-level SKILL lives one level above
    the Pack root (``factory/app_builder/SKILL.md``), which is a fixed,
    install-controlled location.
    """

    __slots__ = ("_pack_root", "_top_level_skill")

    def __init__(self, *, pack_root: Path) -> None:
        if not isinstance(pack_root, Path):
            raise TypeError("pack_root must be a Path")
        self._pack_root = pack_root.resolve()
        # V1 top-level: factory/app_builder/SKILL.md == pack_root.parent.
        self._top_level_skill = self._pack_root.parent / "SKILL.md"

    def top_level_skill_path(self) -> str | None:
        """Absolute path of the top-level SKILL.md, or ``None`` if absent."""
        target = self._top_level_skill
        if target.is_file():
            return str(target)
        return None

    def pack_skill_path(self, model_id: str, file_name: str) -> str | None:
        """Absolute path of ``<pack_root>/<model_id>/<file_name>``.

        Returns ``None`` when the path escapes the Pack root or the file
        does not exist.
        """
        if not model_id or not file_name:
            return None
        target = (self._pack_root / model_id / file_name).resolve()
        try:
            target.relative_to(self._pack_root)
        except ValueError:
            return None
        if not target.is_file():
            return None
        return str(target)
