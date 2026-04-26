"""FastAPI server for the Creative Boardroom orchestrator.

Run:
    uvicorn orchestrator.server:app --port 8000
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from orchestrator import debate, evidence_store
from orchestrator.a2a import DebateRequest


BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_PATH = Path(os.getenv("PARQUET_PATH", str(BASE_DIR / "pipeline/creative_features.parquet")))
CAMPAIGN_ID = os.getenv("CAMPAIGN_ID", "")

app = FastAPI(title="Creative Boardroom Orchestrator")


@app.on_event("startup")
async def startup() -> None:
    evidence_store.init_db()
    if PARQUET_PATH.exists():
        try:
            rows = debate.load_creative_rows(PARQUET_PATH)
            print(f"[orchestrator] Loaded {len(rows)} creatives from {PARQUET_PATH}")
        except Exception as exc:
            print(f"[orchestrator] Could not preload {PARQUET_PATH}: {exc}")
    else:
        print(
            f"[orchestrator] {PARQUET_PATH} not found; using one in-code demo creative."
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agents")
async def agents() -> list[dict[str, Any]]:
    cards = await debate.discover_agents()
    return [card.model_dump(mode="json") for card in cards]


@app.get("/creatives")
def list_creatives() -> list[dict[str, Any]]:
    try:
        rows = debate.load_creative_rows(PARQUET_PATH)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    cols = [
        "creative_id",
        "campaign_id",
        "format",
        "ctr",
        "ipm",
        "cvr",
        "spend",
        "installs",
        "conversions",
        "ctr_pct",
        "ipm_pct",
        "spend_pct",
        "cvr_pct",
        "image_path",
        "creative_status",
        "perf_score",
        "theme",
        "emotional_tone",
        "language",
    ]
    return [{key: row.get(key) for key in cols if key in row} for row in rows]


@app.get("/creatives/{creative_id}")
def get_creative(creative_id: str) -> dict[str, Any]:
    try:
        return debate.load_creative_context(creative_id, PARQUET_PATH)
    except debate.CreativeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/debate")
async def run_debate(req: DebateRequest) -> dict[str, Any]:
    try:
        task = debate.build_task(
            req.creative_id,
            parquet_path=PARQUET_PATH,
            campaign_id=CAMPAIGN_ID,
        )
    except debate.CreativeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = await debate.run_debate(task)
    payload = result.model_dump(mode="json")
    evidence_store.save_debate_result(result.debate_id, result.creative_id, result)
    return payload


@app.post("/debate/start")
async def start_debate(req: DebateRequest) -> dict[str, str]:
    try:
        task = debate.build_task(
            req.creative_id,
            parquet_path=PARQUET_PATH,
            campaign_id=CAMPAIGN_ID,
        )
    except debate.CreativeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def run_and_store() -> None:
        try:
            result = await debate.run_debate(task)
            evidence_store.save_debate_result(result.debate_id, result.creative_id, result)
        except Exception as exc:
            evidence_store.log_event(
                task.task_id,
                task.creative_id,
                99,
                "server_error",
                "orchestrator",
                {"error": str(exc)},
            )

    asyncio.create_task(run_and_store())
    return {
        "debate_id": task.task_id,
        "creative_id": task.creative_id,
        "campaign_id": task.campaign_id,
    }


@app.get("/debate/{debate_id}")
def get_debate(debate_id: str) -> dict[str, Any]:
    result = evidence_store.get_debate_result(debate_id)
    if result is not None:
        result.setdefault("events", evidence_store.get_debate_log(debate_id))
        return result

    events = evidence_store.get_debate_log(debate_id)
    if events:
        return {"debate_id": debate_id, "events": events}
    raise HTTPException(status_code=404, detail="Debate not found")


@app.get("/debate/{creative_id}/result")
def get_cached_result_for_creative(creative_id: str) -> dict[str, Any]:
    result = evidence_store.get_latest_debate_result_for_creative(creative_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No cached result for this creative")
    debate_id = str(result.get("debate_id") or "")
    if debate_id:
        result.setdefault("events", evidence_store.get_debate_log(debate_id))
    return result
