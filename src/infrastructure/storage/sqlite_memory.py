import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from ...core.models import MemoryCategory, MemoryEntry, MemoryScope
from ...core.ports import IMemoryRepository
from ...core.services.redaction import compute_content_hash
from .migrations import run_migrations

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def to_fts_query(query: str) -> Optional[str]:
    """Sanitizes arbitrary user/LLM text into safe FTS5 prefix tokens joined with OR."""
    tokens = [t for t in _FTS_TOKEN_RE.findall(query) if t.strip()]
    if not tokens:
        return None
    return " OR ".join(f'"{tok}"*' for tok in tokens)


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


class SqliteMemoryRepository(IMemoryRepository):
    """SQLite persistence adapter with FTS5 + BM25, schema migrations, versioning, and Upsert."""

    def __init__(self, db_path: str = "./data/agent_memory.db", force_like_fallback: bool = False):
        self.db_path = str(db_path)
        fts_ready = run_migrations(self.db_path)
        self.fts_enabled = fts_ready and not force_like_fallback

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def save_memory(
        self, memory: MemoryEntry, supersedes: Optional[int] = None
    ) -> MemoryEntry:
        clean_content = memory.content.strip()
        clean_project = memory.project_name.strip() if memory.project_name else None
        c_hash = compute_content_hash(clean_content, clean_project)
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat()

        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    SELECT id, tags, created_at FROM memories
                    WHERE content_hash = ? AND superseded_by IS NULL
                    LIMIT 1
                    """,
                    (c_hash,),
                )
                existing = cursor.fetchone()

                if existing:
                    existing_id = int(existing["id"])
                    existing_tags = self._parse_tags(existing["tags"])
                    merged_tags = sorted(list(set(existing_tags + memory.tags)))
                    tags_str = json.dumps(merged_tags)

                    cursor.execute(
                        """
                        UPDATE memories
                        SET category = ?, tags = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (memory.category.value, tags_str, now_iso, existing_id),
                    )
                    if supersedes is not None and supersedes != existing_id:
                        cursor.execute(
                            "UPDATE memories SET superseded_by = ?, updated_at = ? WHERE id = ?",
                            (existing_id, now_iso, supersedes),
                        )

                    memory.id = existing_id
                    memory.content = clean_content
                    memory.project_name = clean_project
                    memory.tags = merged_tags
                    memory.content_hash = c_hash
                    memory.created_at = self._parse_dt(existing["created_at"]) or now_utc
                    memory.updated_at = now_utc
                    return memory

                tags_str = json.dumps(sorted(list(set(memory.tags))))
                cursor.execute(
                    """
                    INSERT INTO memories (
                        category, content, project_name, tags,
                        created_at, updated_at, content_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory.category.value,
                        clean_content,
                        clean_project,
                        tags_str,
                        now_iso,
                        now_iso,
                        c_hash,
                    ),
                )
                new_id = int(cursor.lastrowid)

                if supersedes is not None and supersedes != new_id:
                    cursor.execute(
                        "UPDATE memories SET superseded_by = ?, updated_at = ? WHERE id = ?",
                        (new_id, now_iso, supersedes),
                    )

                memory.id = new_id
                memory.content = clean_content
                memory.project_name = clean_project
                memory.content_hash = c_hash
                memory.created_at = now_utc
                memory.updated_at = now_utc
                return memory
        finally:
            conn.close()

    def search_memories(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        clean_proj = project_name.strip() if project_name and project_name.strip() else None
        fts_expr = to_fts_query(query) if query else None

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if fts_expr and self.fts_enabled:
                where_clauses = ["memories_fts MATCH ?"]
                params: List[object] = [fts_expr]

                if not include_history:
                    where_clauses.append("m.superseded_by IS NULL")
                if category:
                    where_clauses.append("m.category = ?")
                    params.append(category.value)

                self._append_scope_filter(where_clauses, params, clean_proj, scope, alias="m.")

                sql = f"""
                    SELECT m.id, m.category, m.content, m.project_name, m.tags,
                           m.created_at, m.updated_at, m.last_used_at, m.superseded_by, m.content_hash,
                           bm25(memories_fts, 10.0, 4.0, 1.0) AS score
                    FROM memories_fts
                    JOIN memories m ON m.id = memories_fts.rowid
                    WHERE {' AND '.join(where_clauses)}
                    ORDER BY score ASC, m.id DESC
                    LIMIT ?
                """
                params.append(limit)
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                entities = [self._row_to_entity(r) for r in rows]
                self._touch_last_used(conn, [e.id for e in entities if e.id is not None])
                return entities

            # Fallback path (or empty query): SQL query + accent-insensitive Python token ranking
            where_clauses = ["1=1"]
            params = []
            if not include_history:
                where_clauses.append("superseded_by IS NULL")
            if category:
                where_clauses.append("category = ?")
                params.append(category.value)

            self._append_scope_filter(where_clauses, params, clean_proj, scope, alias="")

            tokens = [
                _strip_accents(t.lower())
                for t in _FTS_TOKEN_RE.findall(query)
                if t.strip()
            ] if query else []

            sql = f"""
                SELECT id, category, content, project_name, tags,
                       created_at, updated_at, last_used_at, superseded_by, content_hash
                FROM memories
                WHERE {' AND '.join(where_clauses)}
                ORDER BY id DESC
            """
            if not tokens:
                sql += " LIMIT ?"
                params.append(limit)
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                entities = [self._row_to_entity(r) for r in rows]
                self._touch_last_used(conn, [e.id for e in entities if e.id is not None])
                return entities

            cursor.execute(sql, params)
            all_candidates = [self._row_to_entity(r) for r in cursor.fetchall()]

            scored: List[tuple[int, MemoryEntry]] = []
            for ent in all_candidates:
                haystack = _strip_accents(
                    f"{ent.content} {' '.join(ent.tags)} {ent.project_name or ''}".lower()
                )
                matched = sum(1 for tok in tokens if tok in haystack)
                if matched > 0:
                    scored.append((matched, ent))

            scored.sort(key=lambda pair: (pair[0], pair[1].id or 0), reverse=True)
            result_entities = [pair[1] for pair in scored[:limit]]
            self._touch_last_used(conn, [e.id for e in result_entities if e.id is not None])
            return result_entities
        finally:
            conn.close()

    def list_memories(
        self,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        clean_proj = project_name.strip() if project_name and project_name.strip() else None
        where_clauses = ["1=1"]
        params: List[object] = []

        if not include_history:
            where_clauses.append("superseded_by IS NULL")

        # Note: for list_memories, if project_name is given with default ALL, list exact project unless GLOBAL
        eff_scope = (
            MemoryScope.PROJECT
            if (clean_proj and scope == MemoryScope.ALL)
            else scope
        )
        self._append_scope_filter(where_clauses, params, clean_proj, eff_scope, alias="")

        sql = f"""
            SELECT id, category, content, project_name, tags,
                   created_at, updated_at, last_used_at, superseded_by, content_hash
            FROM memories
            WHERE {' AND '.join(where_clauses)}
            ORDER BY id DESC
            LIMIT ?
        """
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [self._row_to_entity(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def list_stale_memories(self, days: int = 180) -> List[MemoryEntry]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        sql = """
            SELECT id, category, content, project_name, tags,
                   created_at, updated_at, last_used_at, superseded_by, content_hash
            FROM memories
            WHERE superseded_by IS NULL
              AND COALESCE(last_used_at, updated_at, created_at) < ?
            ORDER BY COALESCE(last_used_at, updated_at, created_at) ASC
            LIMIT 100
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(sql, (cutoff,)).fetchall()
            return [self._row_to_entity(r) for r in rows]
        finally:
            conn.close()

    def delete_memory(self, memory_id: int) -> bool:
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                return cursor.rowcount > 0
        finally:
            conn.close()

    def _append_scope_filter(
        self,
        where_clauses: List[str],
        params: List[object],
        clean_proj: Optional[str],
        scope: MemoryScope,
        alias: str,
    ) -> None:
        if scope == MemoryScope.GLOBAL:
            where_clauses.append(f"{alias}project_name IS NULL")
        elif scope == MemoryScope.PROJECT and clean_proj:
            where_clauses.append(f"LOWER({alias}project_name) = LOWER(?)")
            params.append(clean_proj)
        elif clean_proj:
            # MemoryScope.ALL with project_name combines project-specific + global memories
            where_clauses.append(
                f"(LOWER({alias}project_name) = LOWER(?) OR {alias}project_name IS NULL)"
            )
            params.append(clean_proj)

    def _touch_last_used(self, conn: sqlite3.Connection, ids: List[int]) -> None:
        if not ids:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        with conn:
            conn.execute(
                f"UPDATE memories SET last_used_at = ? WHERE id IN ({placeholders})",
                [now_iso, *ids],
            )

    @staticmethod
    def _parse_tags(raw_tags: Optional[str]) -> List[str]:
        if not raw_tags:
            return []
        try:
            parsed = json.loads(raw_tags)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except Exception:
            pass
        return [t.strip() for t in raw_tags.split(",") if t.strip()]

    @staticmethod
    def _parse_dt(raw_dt: Optional[str]) -> Optional[datetime]:
        if not raw_dt:
            return None
        try:
            return datetime.fromisoformat(raw_dt)
        except Exception:
            return None

    def _row_to_entity(self, row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            project_name=row["project_name"],
            tags=self._parse_tags(row["tags"]),
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
            last_used_at=self._parse_dt(row["last_used_at"]),
            superseded_by=row["superseded_by"],
            content_hash=row["content_hash"],
        )


class InMemoryMemoryRepository(IMemoryRepository):
    """Pure in-memory implementation of IMemoryRepository for fast unit and contract testing."""

    def __init__(self) -> None:
        self._items: Dict[int, MemoryEntry] = {}
        self._next_id = 1

    def save_memory(
        self, memory: MemoryEntry, supersedes: Optional[int] = None
    ) -> MemoryEntry:
        clean_content = memory.content.strip()
        clean_project = memory.project_name.strip() if memory.project_name else None
        c_hash = compute_content_hash(clean_content, clean_project)
        now_utc = datetime.now(timezone.utc)

        for existing in self._items.values():
            if existing.content_hash == c_hash and existing.superseded_by is None:
                existing.category = memory.category
                existing.tags = sorted(list(set(existing.tags + memory.tags)))
                existing.updated_at = now_utc
                if supersedes is not None and supersedes in self._items and supersedes != existing.id:
                    self._items[supersedes].superseded_by = existing.id
                return existing.model_copy(deep=True)

        assigned_id = self._next_id
        self._next_id += 1
        saved = MemoryEntry(
            id=assigned_id,
            category=memory.category,
            content=clean_content,
            project_name=clean_project,
            tags=sorted(list(set(memory.tags))),
            created_at=now_utc,
            updated_at=now_utc,
            content_hash=c_hash,
            redacted_labels=list(memory.redacted_labels),
        )
        self._items[assigned_id] = saved
        if supersedes is not None and supersedes in self._items and supersedes != assigned_id:
            self._items[supersedes].superseded_by = assigned_id
        return saved.model_copy(deep=True)

    def search_memories(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        clean_proj = project_name.strip().lower() if project_name and project_name.strip() else None
        tokens = [
            _strip_accents(t.lower())
            for t in _FTS_TOKEN_RE.findall(query)
            if t.strip()
        ] if query else []

        candidates: List[tuple[int, MemoryEntry]] = []
        for item in self._items.values():
            if not include_history and item.superseded_by is not None:
                continue
            if category and item.category != category:
                continue

            item_proj = item.project_name.lower() if item.project_name else None
            if scope == MemoryScope.GLOBAL and item_proj is not None:
                continue
            if scope == MemoryScope.PROJECT and clean_proj and item_proj != clean_proj:
                continue
            if scope == MemoryScope.ALL and clean_proj and item_proj not in (clean_proj, None):
                continue

            if not tokens:
                candidates.append((1, item))
            else:
                haystack = _strip_accents(
                    f"{item.content} {' '.join(item.tags)} {item.project_name or ''}".lower()
                )
                score = sum(1 for tok in tokens if tok in haystack)
                if score > 0:
                    candidates.append((score, item))

        candidates.sort(key=lambda p: (p[0], p[1].id or 0), reverse=True)
        now_utc = datetime.now(timezone.utc)
        out: List[MemoryEntry] = []
        for _, ent in candidates[:limit]:
            ent.last_used_at = now_utc
            out.append(ent.model_copy(deep=True))
        return out

    def list_memories(
        self,
        project_name: Optional[str] = None,
        scope: MemoryScope = MemoryScope.ALL,
        include_history: bool = False,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        clean_proj = project_name.strip().lower() if project_name and project_name.strip() else None
        eff_scope = MemoryScope.PROJECT if (clean_proj and scope == MemoryScope.ALL) else scope
        out: List[MemoryEntry] = []
        for item in sorted(self._items.values(), key=lambda x: x.id or 0, reverse=True):
            if not include_history and item.superseded_by is not None:
                continue
            item_proj = item.project_name.lower() if item.project_name else None
            if eff_scope == MemoryScope.GLOBAL and item_proj is not None:
                continue
            if eff_scope == MemoryScope.PROJECT and clean_proj and item_proj != clean_proj:
                continue
            out.append(item.model_copy(deep=True))
            if len(out) >= limit:
                break
        return out

    def list_stale_memories(self, days: int = 180) -> List[MemoryEntry]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        out: List[MemoryEntry] = []
        for item in self._items.values():
            if item.superseded_by is not None:
                continue
            ref_dt = item.last_used_at or item.updated_at or item.created_at
            if ref_dt and ref_dt < cutoff:
                out.append(item.model_copy(deep=True))
        return out

    def delete_memory(self, memory_id: int) -> bool:
        return self._items.pop(memory_id, None) is not None
