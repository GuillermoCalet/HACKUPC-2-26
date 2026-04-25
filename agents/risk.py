"""
Risk Officer agent — Port 8003.

Evaluates financial exposure and statistical confidence.
Model: configured by LLM_PROVIDER / OLLAMA_MODEL_TEXT.
"""
import json
import math

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents.llm_client import generate_text
from agents._agent_helpers import (
    load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)

CARD = AgentCard(
    name="risk_officer",
    description="Evaluates financial exposure and statistical confidence for creative investment decisions",
    skills=["analyze_risk", "respond_to_challenge"],
    endpoint="http://localhost:8003",
    vote_weight=0.8,
)

def _metric(context: dict, *names: str, default: float = 0.0) -> float:
    for name in names:
        value = context.get(name)
        if value not in (None, ""):
            return float(value)
    return default


def _wilson_interval(count: int, nobs: int, z: float = 1.96) -> tuple[float, float]:
    if nobs <= 0:
        return 0.0, 1.0
    phat = count / nobs
    denom = 1 + z**2 / nobs
    center = (phat + z**2 / (2 * nobs)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z**2 / (4 * nobs)) / nobs) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _compute_stats(context: dict) -> str:
    installs = int(_metric(context, "installs", "total_conversions", "conversions", default=0))
    impressions = int(_metric(context, "impressions", "total_impressions", default=1))
    spend = _metric(context, "spend", "total_spend_usd", "spend_usd", default=0)
    clicks = _metric(context, "clicks", "total_clicks", default=0)
    cpi = _metric(context, "cpi", default=spend / installs if installs else 0)

    try:
        ci_low, ci_high = _wilson_interval(count=installs, nobs=impressions)
        ci_width = float(ci_high - ci_low)
    except Exception:
        ci_low, ci_high, ci_width = 0.0, 0.0, 1.0

    return json.dumps({
        "spend": spend,
        "spend_pct": context.get("spend_pct", 0),
        "installs": installs,
        "clicks": clicks,
        "impressions": impressions,
        "cpi": cpi,
        "overall_roas": context.get("overall_roas", 0),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "ci_width": round(ci_width, 6),
        "high_spend_unreliable": context.get("spend_pct", 0) > 0.7 and ci_width > 0.005,
        "losing_money": (context.get("overall_roas") or 0) < 0.8,
        "reliable_profitable": ci_width < 0.002 and (context.get("overall_roas") or 0) > 1.2,
    }, indent=2, default=str)


async def opinion_fn(task: Task, prior_messages: list[Message]) -> Opinion:
    round_num = 3 if prior_messages else 1
    prompt = load_prompt("risk")
    user_msg = (
        prompt
        .replace("{context}", context_str(task.context))
        .replace("{stats}", _compute_stats(task.context))
        .replace("{challenges}", challenges_str(prior_messages))
    )
    raw = generate_text(user_msg, max_tokens=1024)
    return parse_opinion(raw, CARD.name, round_num)


async def respond_fn(task: Task, opinions: list[Opinion]) -> list[Message]:
    prompt = load_prompt("respond")
    user_msg = (
        prompt
        .replace("{agent_name}", CARD.name)
        .replace("{context}", context_str(task.context))
        .replace("{opinions}", opinions_str(opinions))
    )
    raw = generate_text(user_msg, max_tokens=1024)
    return parse_messages(raw, CARD.name)


app = make_agent(CARD, opinion_fn, respond_fn)
