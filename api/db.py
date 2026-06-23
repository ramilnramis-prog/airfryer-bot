"""Очередь задач на SQLite. Статусы: queued / processing / ready / failed."""
import sqlite3
import json
import time
from .config import DB_PATH


def _connect():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = _connect()
    try:
        c.execute(
            """CREATE TABLE IF NOT EXISTS jobs(
                job_id     TEXT PRIMARY KEY,
                type       TEXT,
                status     TEXT,
                result     TEXT,
                error      TEXT,
                created_at REAL,
                updated_at REAL
            )"""
        )
        c.commit()
    finally:
        c.close()


def create_job(job_id: str, job_type: str):
    now = time.time()
    c = _connect()
    try:
        c.execute(
            "INSERT INTO jobs(job_id,type,status,result,error,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (job_id, job_type, "queued", None, None, now, now),
        )
        c.commit()
    finally:
        c.close()


def set_status(job_id: str, status: str, result=None, error=None):
    c = _connect()
    try:
        c.execute(
            "UPDATE jobs SET status=?, result=?, error=?, updated_at=? WHERE job_id=?",
            (
                status,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error,
                time.time(),
                job_id,
            ),
        )
        c.commit()
    finally:
        c.close()


def get_job(job_id: str):
    c = _connect()
    try:
        row = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    finally:
        c.close()
    if not row:
        return None
    return {
        "job_id": row["job_id"],
        "type": row["type"],
        "status": row["status"],
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
    }
