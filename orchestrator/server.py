"""
Orchestrator server.

Usage:
    uvicorn orchestrator.server:app --port 8000

Endpoints:
    GET  /creatives          — list all creatives in the selected campaign
    GET  /creatives/{id}     — get one creative's context row
    POST /debate             — run a full boardroom debate for a creative
    GET  /debate/{id}/result — retrieve a cached debate result
"""
import os
import uuid
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from orchestrator.a2a import Task
from orchestrator import debate as debate_module
from orchestrator import evidence_store
from synthesizer.synthesize import synthesize

load_dotenv()

PARQUET_PATH = Path(os.getenv("PARQUET_PATH", "pipeline/creative_features.parquet"))
CAMPAIGN_ID = os.getenv("CAMPAIGN_ID", "")

app = FastAPI(title="Creative Boardroom Orchestrator")

_df: pd.DataFrame | None = None


def _load_df() -> pd.DataFrame:
    global _df
    if _df is None:
        if not PARQUET_PATH.exists():
            raise RuntimeError(f"Parquet not found at {PARQUET_PATH}. Run: python -m pipeline.build_table")
        _df = pd.read_parquet(PARQUET_PATH)
        _df["creative_id"] = _df["creative_id"].astype(str)
    return _df


@app.on_event("startup")
def startup():
    evidence_store.init_db()
    try:
        _load_df()
        print(f"Loaded {len(_load_df())} creatives")
    except RuntimeError as e:
        print(f"Warning: {e}")


class DebateRequest(BaseModel):
    creative_id: str


@app.get("/creatives")
def list_creatives():
    df = _load_df()
    cols = ["creative_id", "campaign_id", "format", "ctr", "ipm", "cvr", "spend",
            "installs", "ctr_pct", "ipm_pct", "spend_pct", "image_path",
            "creative_status", "perf_score", "theme", "emotional_tone", "language"]
    available = [c for c in cols if c in df.columns]
    return df[available].to_dict(orient="records")


@app.get("/creatives/{creative_id}")
def get_creative(creative_id: str):
    df = _load_df()
    row = df[df["creative_id"] == creative_id]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Creative {creative_id} not found")
    return row.iloc[0].to_dict()


@app.post("/debate")
async def run_debate(req: DebateRequest):
    df = _load_df()
    row = df[df["creative_id"] == req.creative_id]
    if row.empty:
        raise HTTPException(status_code=404, detail=f"Creative {req.creative_id} not found")

    context = row.iloc[0].to_dict()
    # JSON-serialisable context (convert timestamps/numpy types)
    context = {k: (v.isoformat() if hasattr(v, "isoformat") else (float(v) if hasattr(v, "item") else v))
               for k, v in context.items()}

    image_path = context.get("image_path", "")
    task = Task(
        task_id=str(uuid.uuid4()),
        creative_id=req.creative_id,
        campaign_id=str(context.get("campaign_id", CAMPAIGN_ID)),
        context=context,
        image_path=image_path,
    )

    result = await debate_module.run_debate(task)

    verdict_card = synthesize(
        transcript=result["transcript"],
        final_opinions=result["final_opinions"],
        context=context,
        weighted_verdict=result["weighted_verdict"],
    )

    full_result = {
        "debate_id": task.task_id,
        "creative_id": req.creative_id,
        "verdict_card": verdict_card,
        "transcript": result["transcript"],
        "final_opinions": result["final_opinions"],
        "weighted_verdict": result["weighted_verdict"],
    }

    evidence_store.save_debate_result(task.task_id, req.creative_id, full_result)
    evidence_store.log_event(
        task.task_id, req.creative_id, 4, "synthesis", "orchestrator", verdict_card
    )

    return full_result


@app.get("/debate/{creative_id}/result")
def get_cached_result(creative_id: str):
    result = evidence_store.get_debate_result(creative_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No cached result for this creative")
    return result
