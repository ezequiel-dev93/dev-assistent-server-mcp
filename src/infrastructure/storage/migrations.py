import os
import sqlite3
from pathlib import Path
from ...core.services.redaction import compute_content_hash

LATEST_SCHEMA_VERSION = 4


def probe_fts5_available(conn: sqlite3.Connection) -> bool:
    """Checks whether the active SQLite build includes the FTS5 extension."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x);")
        conn.execute("DROP TABLE temp._fts5_probe;")
        return True
    except sqlite3.OperationalError:
        return False


def _backup_database_file(conn: sqlite3.Connection, db_path: str, current_version: int) -> None:
    if db_path == ":memory:" or not os.path.isfile(db_path):
        return
    try:
        if os.path.getsize(db_path) == 0:
            return
    except OSError:
        return

    bak_path = f"{db_path}.bak-v{current_version}"
    if os.path.exists(bak_path):
        return

    bak_conn = sqlite3.connect(bak_path)
    try:
        conn.backup(bak_conn)
    finally:
        bak_conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return any(row[1] == column for row in cur.fetchall())


def run_migrations(db_path: str) -> bool:
    """
    Runs incremental SQLite schema migrations up to LATEST_SCHEMA_VERSION.
    Returns True if FTS5 full-text indexing is active on this database.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 5000;")
        if db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")

        cur_ver = int(conn.execute("PRAGMA user_version;").fetchone()[0])
        has_fts5 = probe_fts5_available(conn)

        if cur_ver < LATEST_SCHEMA_VERSION and cur_ver > 0:
            _backup_database_file(conn, db_path, cur_ver)
        elif cur_ver == 0 and db_path != ":memory:" and os.path.isfile(db_path):
            # Existing legacy v1.x DB had user_version = 0; back it up if memories table exists
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memories';"
            ).fetchone()
            if tbl is not None:
                _backup_database_file(conn, db_path, 0)

        # Migration 0 -> 1: Baseline schema
        if cur_ver < 1:
            with conn:
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
                conn.execute("PRAGMA user_version = 1;")
            cur_ver = 1

        # Migration 1 -> 2: Add updated_at without overwriting created_at
        if cur_ver < 2:
            with conn:
                if not _column_exists(conn, "memories", "updated_at"):
                    conn.execute("ALTER TABLE memories ADD COLUMN updated_at TEXT;")
                conn.execute(
                    "UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL;"
                )
                conn.execute("PRAGMA user_version = 2;")
            cur_ver = 2

        # Migration 2 -> 3: FTS5 virtual table + sync triggers + backfill
        if cur_ver < 3:
            with conn:
                if has_fts5:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                            content,
                            tags,
                            project_name,
                            content='memories',
                            content_rowid='id',
                            tokenize = "unicode61 remove_diacritics 2"
                        );
                        """
                    )
                    conn.execute(
                        """
                        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                            INSERT INTO memories_fts(rowid, content, tags, project_name)
                            VALUES (new.id, new.content, COALESCE(new.tags, ''), COALESCE(new.project_name, ''));
                        END;
                        """
                    )
                    conn.execute(
                        """
                        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                            INSERT INTO memories_fts(memories_fts, rowid, content, tags, project_name)
                            VALUES ('delete', old.id, old.content, COALESCE(old.tags, ''), COALESCE(old.project_name, ''));
                        END;
                        """
                    )
                    conn.execute(
                        """
                        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content, tags, project_name ON memories BEGIN
                            INSERT INTO memories_fts(memories_fts, rowid, content, tags, project_name)
                            VALUES ('delete', old.id, old.content, COALESCE(old.tags, ''), COALESCE(old.project_name, ''));
                            INSERT INTO memories_fts(rowid, content, tags, project_name)
                            VALUES (new.id, new.content, COALESCE(new.tags, ''), COALESCE(new.project_name, ''));
                        END;
                        """
                    )
                    conn.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild');")
                conn.execute("PRAGMA user_version = 3;")
            cur_ver = 3

        # Migration 3 -> 4: Versioning (superseded_by), last_used_at, and content_hash
        if cur_ver < 4:
            with conn:
                if not _column_exists(conn, "memories", "superseded_by"):
                    conn.execute(
                        "ALTER TABLE memories ADD COLUMN superseded_by INTEGER REFERENCES memories(id);"
                    )
                if not _column_exists(conn, "memories", "last_used_at"):
                    conn.execute("ALTER TABLE memories ADD COLUMN last_used_at TEXT;")
                if not _column_exists(conn, "memories", "content_hash"):
                    conn.execute("ALTER TABLE memories ADD COLUMN content_hash TEXT;")

                rows = conn.execute(
                    "SELECT id, content, project_name FROM memories WHERE content_hash IS NULL;"
                ).fetchall()
                for r in rows:
                    c_hash = compute_content_hash(r["content"], r["project_name"])
                    conn.execute(
                        "UPDATE memories SET content_hash = ? WHERE id = ?;",
                        (c_hash, r["id"]),
                    )

                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(content_hash);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(superseded_by) WHERE superseded_by IS NULL;"
                )
                conn.execute("PRAGMA user_version = 4;")

        fts_tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts';"
        ).fetchone()
        return bool(has_fts5 and fts_tbl is not None)
    finally:
        conn.close()
