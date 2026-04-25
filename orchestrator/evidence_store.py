"""SQLite logging for Creative Boardroom debates."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel


DB_PATH = Path(os.getenv("EVIDENCE_DB_PATH", "evidence.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS debate_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              debate_id TEXT,
              creative_id TEXT,
              round INTEGER,
              type TEXT,
              agent TEXT,
              payload TEXT,
              ts TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS debate_results (
              debate_id TEXT PRIMARY KEY,
              creative_id TEXT,
              result TEXT,
              ts TEXT
            )
            """
        )
        # Current LLM-backed visual agent uses this cache. It is intentionally
        # separate from the debate protocol log.
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS vision_cache (
              creative_id TEXT PRIMARY KEY,
              analysis TEXT,
              ts TEXT
            )
            """
        )


def log_event(
    debate_id: str,
    creative_id: str,
    round_: int,
    type_: str,
    agent: str,
    payload: Any,
) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            """
            INSERT INTO debate_log
              (debate_id, creative_id, round, type, agent, payload, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                debate_id,
                creative_id,
                round_,
                type_,
                agent,
                json.dumps(_jsonable(payload), default=str),
                _utc_now(),
            ),
        )


def get_debate_log(debate_id: str) -> list[dict[str, Any]]:
    init_db()
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id, debate_id, creative_id, round, type, agent, payload, ts
            FROM debate_log
            WHERE debate_id = ?
            ORDER BY id ASC
            """,
            (debate_id,),
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"])
        except Exception:
            pass
        events.append(item)
    return events


def save_debate_result(debate_id: str, creative_id: str, result: Any) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO debate_results (debate_id, creative_id, result, ts)
            VALUES (?, ?, ?, ?)
            """,
            (
                debate_id,
                creative_id,
                json.dumps(_jsonable(result), default=str),
                _utc_now(),
            ),
        )


def get_debate_result(debate_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as con:
        row = con.execute(
            "SELECT result FROM debate_results WHERE debate_id = ?",
            (debate_id,),
        ).fetchone()
    return json.loads(row["result"]) if row else None


def get_latest_debate_result_for_creative(creative_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as con:
        row = con.execute(
            """
            SELECT result
            FROM debate_results
            WHERE creative_id = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (creative_id,),
        ).fetchone()
    return json.loads(row["result"]) if row else None


def get_vision_cache(creative_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as con:
        row = con.execute(
            "SELECT analysis FROM vision_cache WHERE creative_id = ?",
            (creative_id,),
        ).fetchone()
    return json.loads(row["analysis"]) if row else None


def set_vision_cache(creative_id: str, analysis: dict[str, Any]) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO vision_cache (creative_id, analysis, ts)
            VALUES (?, ?, ?)
            """,
            (creative_id, json.dumps(_jsonable(analysis), default=str), _utc_now()),
        )
