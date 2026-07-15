"""aiosqlite-backed :class:`ModeTemplateRepositoryPort`.

Schema reference: ``qai-db-schema.md`` §2.10 (chat_mode_template, migration
040).  A :class:`~qai.chat.domain.mode_template.ModeTemplate` is a **single-row
aggregate** — its two policy blobs live in ``tool_policy_json`` /
``flow_policy_json`` columns — so :meth:`save` is a single ``BEGIN IMMEDIATE``
upsert with no child-row rewrite (mirroring
:class:`~qai.chat.adapters.roster_template_repository.
SqliteRosterTemplateRepository`).

``is_builtin`` marks factory-seeded preset modes.  A mode is conversation-
independent (no FK); a conversation references its chosen mode via
``meta["discussion"]["selected_mode_id"]``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from qai.chat.domain.errors import ModeTemplateNotFoundError
from qai.chat.domain.ids import ModeTemplateId
from qai.chat.domain.mode_template import (
    ModeFlowPolicy,
    ModeHardConstraints,
    ModeTemplate,
    ModeToolPolicy,
)
from qai.platform.errors import PersistenceError

if TYPE_CHECKING:  # pragma: no cover
    from qai.platform.persistence import Database


__all__ = ["SqliteModeTemplateRepository"]


_COLUMNS = (
    "id, name, description, framing, tool_policy_json, flow_policy_json, "
    "hard_constraints_json, is_builtin, cloned_from_id, created_at, updated_at"
)


def _loads(raw: object) -> dict:
    """Parse a JSON-object column; malformed → empty dict (degrade, not raise)."""
    if raw is None:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class SqliteModeTemplateRepository:
    """aiosqlite implementation of :class:`ModeTemplateRepositoryPort`."""

    __slots__ = ("_db",)

    def __init__(self, *, db: "Database") -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------
    async def save(self, template: ModeTemplate) -> None:
        """Insert or upsert ``template`` (single-row aggregate, by id)."""
        params = (
            template.id.value,
            template.name,
            template.description,
            template.framing,
            json.dumps(template.tool_policy.to_dict(), ensure_ascii=False),
            json.dumps(template.flow_policy.to_dict(), ensure_ascii=False),
            json.dumps(
                template.hard_constraints.to_dict(), ensure_ascii=False
            ),
            1 if template.is_builtin else 0,
            template.cloned_from_id,
            template.created_at.isoformat(),
            template.updated_at.isoformat(),
        )
        try:
            async with self._db.connection() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                try:
                    await conn.execute(
                        "INSERT INTO chat_mode_template ("
                        "id, name, description, framing, tool_policy_json, "
                        "flow_policy_json, hard_constraints_json, is_builtin, "
                        "cloned_from_id, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        " name=excluded.name, "
                        " description=excluded.description, "
                        " framing=excluded.framing, "
                        " tool_policy_json=excluded.tool_policy_json, "
                        " flow_policy_json=excluded.flow_policy_json, "
                        " hard_constraints_json=excluded.hard_constraints_json, "
                        " is_builtin=excluded.is_builtin, "
                        " updated_at=excluded.updated_at",
                        params,
                    )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.mode_template.save_failed",
                f"failed to save mode template {template.id.value!r}: {exc}",
                operation="mode_template.save",
                cause=exc,
            ) from exc

    async def delete(self, template_id: ModeTemplateId) -> None:
        """Remove the template; raise if missing."""
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    "DELETE FROM chat_mode_template WHERE id = ?",
                    (template_id.value,),
                )
                rows_affected = cur.rowcount
                await cur.close()
                await conn.commit()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.mode_template.delete_failed",
                f"failed to delete mode template {template_id.value!r}: {exc}",
                operation="mode_template.delete",
                cause=exc,
            ) from exc
        if rows_affected == 0:
            raise ModeTemplateNotFoundError(template_id.value)

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------
    async def find(
        self,
        template_id: ModeTemplateId,
    ) -> ModeTemplate | None:
        """Return the aggregate or ``None`` if not present."""
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM chat_mode_template WHERE id = ?",
                    (template_id.value,),
                )
                row = await cur.fetchone()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.mode_template.find_failed",
                f"failed to load mode template {template_id.value!r}: {exc}",
                operation="mode_template.find",
                cause=exc,
            ) from exc
        if row is None:
            return None
        return self._row_to_template(row)

    async def get(self, template_id: ModeTemplateId) -> ModeTemplate:
        """Return the aggregate; raise :class:`ModeTemplateNotFoundError`."""
        template = await self.find(template_id)
        if template is None:
            raise ModeTemplateNotFoundError(template_id.value)
        return template

    async def list_all(self) -> tuple[ModeTemplate, ...]:
        """Return every template, built-ins first then by ``created_at`` ASC."""
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM chat_mode_template "
                    "ORDER BY is_builtin DESC, created_at ASC",
                )
                rows = await cur.fetchall()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.mode_template.list_all_failed",
                f"failed to list mode templates: {exc}",
                operation="mode_template.list_all",
                cause=exc,
            ) from exc
        return tuple(self._row_to_template(r) for r in rows)

    # ------------------------------------------------------------------
    # Row -> domain
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_template(row: tuple[object, ...]) -> ModeTemplate:
        return ModeTemplate(
            id=ModeTemplateId.of(str(row[0])),
            name=str(row[1]) if row[1] is not None else "",
            description=str(row[2]) if row[2] is not None else "",
            framing=str(row[3]) if row[3] is not None else "",
            tool_policy=ModeToolPolicy.from_dict(_loads(row[4])),
            flow_policy=ModeFlowPolicy.from_dict(_loads(row[5])),
            hard_constraints=ModeHardConstraints.from_dict(_loads(row[6])),
            is_builtin=bool(row[7]),
            cloned_from_id=str(row[8]) if row[8] is not None else None,
            created_at=datetime.fromisoformat(str(row[9])),
            updated_at=datetime.fromisoformat(str(row[10])),
        )
