import sqlite3
import json
from datetime import datetime

DB_PATH = "evidence.db"


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS debate_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        debate_id TEXT, creative_id TEXT, round INTEGER,
        type TEXT, agent TEXT, payload TEXT, ts TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS vision_cache (
        creative_id TEXT PRIMARY KEY,
        analysis TEXT, ts TEXT
    )""")
    con.commit()
    con.close()


def log_event(debate_id, creative_id, round_, type_, agent, payload):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO debate_log VALUES (NULL,?,?,?,?,?,?,?)",
        (debate_id, creative_id, round_, type_, agent, json.dumps(payload), datetime.utcnow().isoformat()),
    )
    con.commit()
    con.close()


def get_vision_cache(creative_id: str) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT analysis FROM vision_cache WHERE creative_id=?", (creative_id,)).fetchone()
    con.close()
    return json.loads(row[0]) if row else None


def set_vision_cache(creative_id: str, analysis: dict):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR REPLACE INTO vision_cache VALUES (?,?,?)",
        (creative_id, json.dumps(analysis), datetime.utcnow().isoformat()),
    )
    con.commit()
    con.close()


def save_debate_result(debate_id: str, creative_id: str, result: dict):
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS debate_results (
        debate_id TEXT PRIMARY KEY,
        creative_id TEXT,
        result TEXT,
        ts TEXT
    )""")
    con.execute(
        "INSERT OR REPLACE INTO debate_results VALUES (?,?,?,?)",
        (debate_id, creative_id, json.dumps(result, default=str), datetime.utcnow().isoformat()),
    )
    con.commit()
    con.close()


def get_debate_result(creative_id: str) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute(
            "SELECT result FROM debate_results WHERE creative_id=? ORDER BY ts DESC LIMIT 1",
            (creative_id,),
        ).fetchone()
    except Exception:
        row = None
    con.close()
    return json.loads(row[0]) if row else None
