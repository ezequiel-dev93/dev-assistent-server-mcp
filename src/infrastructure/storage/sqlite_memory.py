import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional
from src.core.models import MemoryCategory, MemoryEntry
from src.core.ports import IMemoryRepository


class SqliteMemoryRepository(IMemoryRepository):
    """Adaptador de infraestructura que persiste la memoria en SQLite local con deduplicación y búsqueda multi-término."""

    def __init__(self, db_path: str = "./data/agent_memory.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    project_name TEXT,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_cat ON memories(category);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_name);"
            )
            conn.commit()
        finally:
            conn.close()

    def save_memory(self, memory: MemoryEntry) -> MemoryEntry:
        clean_content = memory.content.strip()
        clean_project = memory.project_name.strip() if memory.project_name else None
        now_utc = datetime.now(timezone.utc)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Upsert / Deduplicación: verificar si ya existe el mismo contenido para el mismo proyecto
            if clean_project:
                cursor.execute(
                    """
                    SELECT id, tags FROM memories
                    WHERE LOWER(content) = LOWER(?) AND LOWER(project_name) = LOWER(?)
                    LIMIT 1
                    """,
                    (clean_content, clean_project),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, tags FROM memories
                    WHERE LOWER(content) = LOWER(?) AND project_name IS NULL
                    LIMIT 1
                    """,
                    (clean_content,),
                )

            existing = cursor.fetchone()
            if existing:
                existing_id = existing["id"]
                existing_tags = []
                if existing["tags"]:
                    try:
                        existing_tags = json.loads(existing["tags"])
                    except Exception:
                        existing_tags = [t.strip() for t in existing["tags"].split(",") if t.strip()]

                merged_tags = sorted(list(set(existing_tags + memory.tags)))
                tags_str = json.dumps(merged_tags)

                cursor.execute(
                    """
                    UPDATE memories
                    SET category = ?, tags = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
                        memory.category.value,
                        tags_str,
                        now_utc.isoformat(),
                        existing_id,
                    ),
                )
                conn.commit()
                memory.id = existing_id
                memory.tags = merged_tags
                memory.created_at = now_utc
                return memory

            tags_str = json.dumps(memory.tags)
            cursor.execute(
                """
                INSERT INTO memories (category, content, project_name, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    memory.category.value,
                    clean_content,
                    clean_project,
                    tags_str,
                    now_utc.isoformat(),
                ),
            )
            conn.commit()
            memory.id = cursor.lastrowid
            memory.created_at = now_utc
            return memory
        finally:
            conn.close()

    def search_memories(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
    ) -> List[MemoryEntry]:
        sql = "SELECT id, category, content, project_name, tags, created_at FROM memories WHERE 1=1"
        params = []

        if category:
            sql += " AND category = ?"
            params.append(category.value)

        if project_name:
            sql += " AND LOWER(project_name) = LOWER(?)"
            params.append(project_name.strip())

        tokens = [t.lower() for t in query.strip().split() if t.strip()] if query else []

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if not tokens:
                sql += " ORDER BY id DESC LIMIT 50"
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [self._row_to_entity(row) for row in rows]

            # Primero intentar coincidencia donde TODOS los tokens aparezcan en content, tags o project_name
            all_tokens_sql = sql
            all_tokens_params = list(params)
            for token in tokens:
                all_tokens_sql += (
                    " AND (LOWER(content) LIKE ? OR LOWER(tags) LIKE ? OR LOWER( COALESCE(project_name, '') ) LIKE ?)"
                )
                like_tok = f"%{token}%"
                all_tokens_params.extend([like_tok, like_tok, like_tok])

            all_tokens_sql += " ORDER BY id DESC LIMIT 50"
            cursor.execute(all_tokens_sql, all_tokens_params)
            rows = cursor.fetchall()
            if rows:
                return [self._row_to_entity(row) for row in rows]

            # Fallback: coincidencia parcial (OR entre tokens) ordenada por cantidad de tokens coincidentes
            any_token_clauses = []
            any_token_params = list(params)
            for token in tokens:
                any_token_clauses.append(
                    "(LOWER(content) LIKE ? OR LOWER(tags) LIKE ? OR LOWER( COALESCE(project_name, '') ) LIKE ?)"
                )
                like_tok = f"%{token}%"
                any_token_params.extend([like_tok, like_tok, like_tok])

            or_sql = f"{sql} AND ({' OR '.join(any_token_clauses)}) ORDER BY id DESC LIMIT 50"
            cursor.execute(or_sql, any_token_params)
            fallback_rows = cursor.fetchall()
            entities = [self._row_to_entity(r) for r in fallback_rows]

            def score_entity(e: MemoryEntry) -> int:
                haystack = f"{e.content} {' '.join(e.tags)} {e.project_name or ''}".lower()
                return sum(1 for tok in tokens if tok in haystack)

            entities.sort(key=lambda e: (score_entity(e), e.id or 0), reverse=True)
            return entities
        finally:
            conn.close()

    def list_memories(
        self, project_name: Optional[str] = None, limit: int = 50
    ) -> List[MemoryEntry]:
        sql = "SELECT id, category, content, project_name, tags, created_at FROM memories"
        params = []
        if project_name:
            sql += " WHERE LOWER(project_name) = LOWER(?)"
            params.append(project_name.strip())

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_entity(row) for row in rows]
        finally:
            conn.close()

    def delete_memory(self, memory_id: int) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _row_to_entity(self, row: sqlite3.Row) -> MemoryEntry:
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                tags = [t.strip() for t in row["tags"].split(",") if t.strip()]

        created_dt = None
        if row["created_at"]:
            try:
                created_dt = datetime.fromisoformat(row["created_at"])
            except Exception:
                created_dt = None

        return MemoryEntry(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            project_name=row["project_name"],
            tags=tags,
            created_at=created_dt,
        )
