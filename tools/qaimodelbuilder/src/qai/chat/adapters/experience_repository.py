"""aiosqlite-backed :class:`ExperienceRepositoryPort` (PR-042).

Schema reference: ``qai-db-schema.md`` §2.4 (chat_experience).
Single-row aggregate -- INSERT OR REPLACE on save, DELETE on delete.

PR-095 (S9 audit §2.3 A-3 experience category counts) appends the
:meth:`list_categories_with_counts` reader.  The existing
:meth:`list_categories` keeps its ``tuple[str, ...]`` return contract
unchanged so historical callers continue to compile.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from qai.chat.domain.errors import ExperienceNotFoundError
from qai.chat.domain.experience import CategoryStat, Experience
from qai.chat.domain.ids import ExperienceId
from qai.platform.errors import PersistenceError

if TYPE_CHECKING:  # pragma: no cover
    from qai.platform.persistence import Database


__all__ = ["SqliteExperienceRepository"]


_COLUMNS = "id, category, content, metadata_json, created_at"


class SqliteExperienceRepository:
    """aiosqlite implementation of :class:`ExperienceRepositoryPort`."""

    __slots__ = ("_db",)

    def __init__(self, *, db: "Database") -> None:
        self._db = db

    async def save(self, experience: Experience) -> None:
        """Insert or replace ``experience`` keyed by id."""
        params = (
            experience.id.value,
            experience.category,
            experience.content,
            json.dumps(experience.metadata),
            experience.created_at.isoformat(),
        )
        try:
            async with self._db.connection() as conn:
                try:
                    await conn.execute(
                        "INSERT INTO chat_experience "
                        "(id, category, content, metadata_json, created_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        " category=excluded.category, "
                        " content=excluded.content, "
                        " metadata_json=excluded.metadata_json",
                        params,
                    )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.save_failed",
                f"failed to save experience {experience.id.value!r}: {exc}",
                operation="experience.save",
                cause=exc,
            ) from exc

    async def get(self, experience_id: ExperienceId) -> Experience:
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    f"SELECT {_COLUMNS} FROM chat_experience WHERE id = ?",
                    (experience_id.value,),
                )
                row = await cur.fetchone()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.get_failed",
                f"failed to load experience {experience_id.value!r}: {exc}",
                operation="experience.get",
                cause=exc,
            ) from exc
        if row is None:
            raise ExperienceNotFoundError(experience_id.value)
        return self._row_to_experience(row)

    async def delete(self, experience_id: ExperienceId) -> None:
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    "DELETE FROM chat_experience WHERE id = ?",
                    (experience_id.value,),
                )
                rows_affected = cur.rowcount
                await cur.close()
                await conn.commit()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.delete_failed",
                f"failed to delete experience {experience_id.value!r}: {exc}",
                operation="experience.delete",
                cause=exc,
            ) from exc
        if rows_affected == 0:
            raise ExperienceNotFoundError(experience_id.value)

    async def list(
        self,
        *,
        category: str | None = None,
        limit: int = 50,
    ) -> tuple[Experience, ...]:
        if limit <= 0:
            return ()
        try:
            async with self._db.connection() as conn:
                if category is None:
                    cur = await conn.execute(
                        f"SELECT {_COLUMNS} FROM chat_experience "
                        "ORDER BY created_at DESC LIMIT ?",
                        (int(limit),),
                    )
                else:
                    cur = await conn.execute(
                        f"SELECT {_COLUMNS} FROM chat_experience "
                        "WHERE category = ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (category, int(limit)),
                    )
                rows = await cur.fetchall()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.list_failed",
                f"failed to list experiences: {exc}",
                operation="experience.list",
                cause=exc,
            ) from exc
        return tuple(self._row_to_experience(r) for r in rows)

    async def list_categories(self) -> tuple[str, ...]:
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    "SELECT DISTINCT category FROM chat_experience "
                    "ORDER BY category ASC"
                )
                rows = await cur.fetchall()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.list_categories_failed",
                f"failed to list categories: {exc}",
                operation="experience.list_categories",
                cause=exc,
            ) from exc
        return tuple(str(r[0]) for r in rows)

    async def list_categories_with_counts(self) -> tuple[CategoryStat, ...]:
        """Return distinct categories with their experience counts.

        PR-095 / S9 A-3.  Restores the legacy "Experience Library"
        sidebar that displayed each category alongside the number
        of saved snippets.  Implemented as a single ``GROUP BY``
        query so the wall-clock cost is comparable to the existing
        :meth:`list_categories` reader.
        """
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(
                    "SELECT category, COUNT(*) AS n FROM chat_experience "
                    "GROUP BY category "
                    "ORDER BY category ASC"
                )
                rows = await cur.fetchall()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.list_categories_with_counts_failed",
                f"failed to list categories with counts: {exc}",
                operation="experience.list_categories_with_counts",
                cause=exc,
            ) from exc
        return tuple(
            CategoryStat(name=str(r[0]), count=int(r[1]))
            for r in rows
        )

    async def search_fulltext(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Experience]:
        """Return experiences matching ``query`` via FTS5 ``MATCH``.

        Backed by the ``experience_fts`` virtual table created in
        migration ``009_chat_experience_fts5.sql`` (PR-094 §17.5 #13 /
        §3.3 A-14). Results are ordered by ``rank`` (FTS5's BM25 default)
        so the most relevant rows surface first.

        Args:
            query: An FTS5 MATCH expression. Callers should sanitize the
                value before invoking — special characters (``"``, ``-``,
                ``*`` etc.) carry FTS5 syntactic meaning. The repository
                does NOT escape the value because doing so opaquely
                would prevent advanced operators (``AND`` / ``OR`` /
                ``NEAR``) that legitimate callers rely on.
            limit: Maximum number of rows to return; non-positive values
                produce an empty list.

        Returns:
            A list (not tuple, by spec) of :class:`Experience` objects
            ordered by relevance, possibly empty when nothing matches or
            when the FTS index has not yet been populated (e.g. the
            migration was just applied and the triggers haven't seen any
            INSERTs yet).
        """
        if not isinstance(query, str):
            raise TypeError(
                f"query must be str, got {type(query).__name__}"
            )
        if limit <= 0:
            return []
        if not query or not query.strip():
            return []

        sql = (
            "SELECT e.id, e.category, e.content, e.metadata_json, e.created_at "
            "FROM experience_fts AS f "
            "JOIN chat_experience AS e ON e.id = f.experience_id "
            "WHERE experience_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ?"
        )
        try:
            async with self._db.connection() as conn:
                cur = await conn.execute(sql, (query, int(limit)))
                rows = await cur.fetchall()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            raise PersistenceError(
                "chat.experience.search_fulltext_failed",
                f"failed to FTS-search experiences: {exc}",
                operation="experience.search_fulltext",
                cause=exc,
            ) from exc
        return [self._row_to_experience(r) for r in rows]

    @staticmethod
    def _row_to_experience(row: tuple[object, ...]) -> Experience:
        metadata_raw = str(row[3] or "{}")
        try:
            metadata = json.loads(metadata_raw)
            if not isinstance(metadata, dict):
                metadata = {}
        except (TypeError, ValueError):
            metadata = {}
        return Experience(
            id=ExperienceId.of(str(row[0])),
            category=str(row[1]),
            content=str(row[2]),
            metadata=metadata,
            created_at=datetime.fromisoformat(str(row[4])),
        )
