"""SQLite 连接、事务与数据库迁移管理。

每次操作新建短连接，配合 WAL 和 busy_timeout 支撑少量并发 worker；
``transaction()`` 使用 BEGIN IMMEDIATE 提前取得写锁，避免读事务升级为写事务时冲突。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utc_now() -> str:
    """返回毫秒精度、带 ``Z`` 后缀的 UTC 时间字符串，便于统一排序和比较。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Database:
    """轻量 SQLite 封装。

    应用只有少量并发 worker，因此采用“一次操作一个连接”的策略，
    把线程安全问题交给 SQLite 自身处理，避免维护长连接池。
    """

    def __init__(self, path: Path) -> None:
        """保存数据库路径并确保父目录存在。"""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """创建启用 WAL、外键约束和忙等待的连接。"""
        # isolation_level=None 关闭 sqlite3 的隐式事务，由 transaction() 显式控制提交。
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL 允许读写并行；外键约束保证删除视频时级联清理关联数据。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """提供自动关闭的普通连接，适合单条查询或独立写入。"""
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """提供显式写事务：正常提交，异常回滚并继续向上抛出。"""
        conn = self.connect()
        try:
            # IMMEDIATE 立即拿写锁，多语句更新期间不会被其他写者插入。
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                # 事务可能已因语句错误自动结束，此时回滚失败可以忽略。
                pass
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        """按文件名前缀顺序执行尚未应用的迁移，每个文件记录一个版本号。"""
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
                # 版本号取文件名第一个下划线之前的部分，例如 0002_xxx.sql -> 0002。
                version = sql_file.name.split("_", 1)[0]
                if version in applied:
                    continue
                sql = sql_file.read_text(encoding="utf-8")
                # 迁移 SQL 与版本记录放在同一事务中执行，避免半应用状态。
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
