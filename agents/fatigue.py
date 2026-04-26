"""
Fatigue Detective agent — Port 8002.

Detects whether a creative is losing effectiveness over time.
Model: configured by LLM_PROVIDER / OLLAMA_MODEL_TEXT.
"""
import json

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents.llm_client import generate_text
from agents._agent_helpers import (
    load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)
from agents.heuristics import fallback_messages, fallback_opinion

CARD = AgentCard(
    name="fatigue_detective",
    description="Detects creative fatigue by analysing performance decay trends and frequency saturation",
    skills=["analyze_fatigue", "respond_to_challenge"],
    endpoint="http://localhost:8002",
    vote_weight=1.0,
)

def _compute_fatigue_signals(context: dict) -> str:
    signals: dict[str, object] = {}
    slope = context.get("ctr_slope_7d", 0.0)
    signals["ctr_slope_7d"] = slope
    signals["strong_decay"] = slope < -0.10
    signals["moderate_decay"] = -0.10 <= slope < -0.05

    decay_pct = context.get("ctr_decay_pct", 0.0)
    signals["ctr_decay_pct"] = decay_pct
    signals["severe_ctr_decay"] = decay_pct < -0.50

    signals["creative_status"] = context.get("creative_status", "unknown")
    signals["fatigue_day"] = context.get("fatigue_day")
    signals["active_days"] = context.get("active_days", 0)
    signals["too_early_to_judge"] = (context.get("active_days", 0) or 0) < 7

    return json.dumps(signals, indent=2, default=str)


async def opinion_fn(
    task: Task,
    prior_messages: list[Message],
    previous_opinion: Opinion | None = None,
) -> Opinion:
    round_num = 3 if prior_messages else 1
    prompt = load_prompt("fatigue")
    user_msg = (
        prompt
        .replace("{context}", context_str(task.context))
        .replace("{fatigue_signals}", _compute_fatigue_signals(task.context))
        .replace("{challenges}", challenges_str(prior_messages))
    )
    try:
        raw = generate_text(user_msg, max_tokens=1024)
        return parse_opinion(raw, CARD.name, round_num)
    except Exception as exc:
        print(f"[{CARD.name}] LLM opinion failed, using fatigue fallback: {exc}")
        return fallback_opinion(CARD.name, task, prior_messages, previous_opinion)


async def respond_fn(task: Task, opinions: list[Opinion]) -> list[Message]:
    prompt = load_prompt("respond")
    user_msg = (
        prompt
        .replace("{agent_name}", CARD.name)
        .replace("{context}", context_str(task.context))
        .replace("{opinions}", opinions_str(opinions))
    )
    try:
        raw = generate_text(user_msg, max_tokens=1024)
        return parse_messages(raw, CARD.name)
    except Exception as exc:
        print(f"[{CARD.name}] LLM respond failed, using fatigue fallback: {exc}")
        return fallback_messages(CARD.name, task, opinions)


app = make_agent(CARD, opinion_fn, respond_fn)
