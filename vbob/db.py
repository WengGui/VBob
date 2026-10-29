from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    """Small SQLite wrapper.

    A fresh connection is opened per operation: the app has a handful of
    concurrent workers, and short-lived connections keep thread-safety simple.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY,"
                "applied_at TEXT NOT NULL"
                ")"
            )
            applied = {
                row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
            }
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = sql_file.name.split("_", 1)[0]
                if version in applied:
                    continue
                sql = sql_file.read_text(encoding="utf-8")
                script = (
                    "BEGIN IMMEDIATE;\n"
                    f"{sql}\n"
                    "INSERT INTO schema_migrations(version, applied_at) VALUES"
                    f"('{version}', '{utc_now()}');\n"
                    "COMMIT;"
                )
                try:
                    conn.executescript(script)
                except BaseException:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.OperationalError:
                        pass
                    raise
