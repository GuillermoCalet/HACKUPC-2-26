"""
Risk Officer agent — Port 8003.

Evaluates financial exposure and statistical confidence.
Model: claude-haiku-4-5-20251001
"""
import json

from scipy.stats import proportion_confint

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents._agent_helpers import (
    get_client, load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)

CARD = AgentCard(
    name="risk_officer",
    description="Evaluates financial exposure and statistical confidence for creative investment decisions",
    skills=["analyze_risk", "respond_to_challenge"],
    endpoint="http://localhost:8003",
    vote_weight=0.8,
)

MODEL = "claude-haiku-4-5-20251001"


def _compute_stats(context: dict) -> str:
    installs = int(context.get("installs", 0) or 0)
    impressions = int(context.get("impressions", 1) or 1)

    try:
        ci_low, ci_high = proportion_confint(
            count=installs, nobs=impressions, alpha=0.05, method="wilson"
        )
        ci_width = float(ci_high - ci_low)
    except Exception:
        ci_low, ci_high, ci_width = 0.0, 0.0, 1.0

    return json.dumps({
        "spend": context.get("spend", 0),
        "spend_pct": context.get("spend_pct", 0),
        "installs": installs,
        "impressions": impressions,
        "cpi": context.get("cpi", 0),
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
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_opinion(response.content[0].text, CARD.name, round_num)


async def respond_fn(task: Task, opinions: list[Opinion]) -> list[Message]:
    prompt = load_prompt("respond")
    user_msg = (
        prompt
        .replace("{agent_name}", CARD.name)
        .replace("{context}", context_str(task.context))
        .replace("{opinions}", opinions_str(opinions))
    )
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": user_msg}],
    )
    return parse_messages(response.content[0].text, CARD.name)


app = make_agent(CARD, opinion_fn, respond_fn)
