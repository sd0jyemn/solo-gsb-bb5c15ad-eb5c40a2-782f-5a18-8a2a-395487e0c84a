"""SQLite 持久化层。

启动时（lifespan）自动建表，数据库文件路径由环境变量 SOA_AUDIT_DB
控制，默认 /data/soa_audit.db（容器内命名卷挂载点）。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

DEFAULT_DB_PATH = "/data/soa_audit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zone        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    result_json TEXT    NOT NULL
);
"""


def db_path() -> str:
    return os.environ.get("SOA_AUDIT_DB", DEFAULT_DB_PATH)


def _connect(path: str | None = None) -> sqlite3.Connection:
    target = path or db_path()
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """幂等建表，随应用启动执行。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI 依赖：每个请求一个连接。"""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def insert_audit(zone: str, created_at: str, result: dict) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO audits (zone, created_at, result_json) VALUES (?, ?, ?)",
            (zone, created_at, json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_audit(audit_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, zone, created_at, result_json FROM audits WHERE id = ?",
            (audit_id,),
        ).fetchone()
    if row is None:
        return None
    result = json.loads(row["result_json"])
    result["id"] = row["id"]
    result["zone"] = row["zone"]
    result["created_at"] = row["created_at"]
    return result
