import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional
from src.core.models import MemoryCategory, MemoryEntry
from src.core.ports import IMemoryRepository


class SqliteMemoryRepository(IMemoryRepository):
    """Adaptador de infraestructura que persiste la memoria en SQLite local."""

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
        tags_str = json.dumps(memory.tags)
        now_utc = datetime.now(timezone.utc)
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (category, content, project_name, tags, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    memory.category.value,
                    memory.content.strip(),
                    memory.project_name.strip() if memory.project_name else None,
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

        if query:
            sql += " AND (content LIKE ? OR tags LIKE ?)"
            like_query = f"%{query.strip()}%"
            params.extend([like_query, like_query])

        if category:
            sql += " AND category = ?"
            params.append(category.value)

        if project_name:
            sql += " AND LOWER(project_name) = LOWER(?)"
            params.append(project_name.strip())

        sql += " ORDER BY id DESC LIMIT 50"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_entity(row) for row in rows]
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
