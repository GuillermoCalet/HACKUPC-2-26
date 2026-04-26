"""
Performance Analyst agent — Port 8001.

Quantifies how a creative performs relative to campaign peers on hard metrics.
Model: configured by LLM_PROVIDER / OLLAMA_MODEL_TEXT.
"""
from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents.llm_client import generate_text
from agents._agent_helpers import (
    load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)
from agents.heuristics import fallback_messages, fallback_opinion

CARD = AgentCard(
    name="performance_analyst",
    description="Quantifies creative performance relative to campaign peers on hard metrics",
    skills=["analyze_performance", "respond_to_challenge"],
    endpoint="http://localhost:8001",
    vote_weight=1.0,
)

async def opinion_fn(
    task: Task,
    prior_messages: list[Message],
    previous_opinion: Opinion | None = None,
) -> Opinion:
    round_num = 3 if prior_messages else 1
    prompt = load_prompt("performance")
    user_msg = (
        prompt
        .replace("{context}", context_str(task.context))
        .replace("{challenges}", challenges_str(prior_messages))
    )
    try:
        raw = generate_text(user_msg, max_tokens=1024)
        return parse_opinion(raw, CARD.name, round_num)
    except Exception as exc:
        print(f"[{CARD.name}] LLM opinion failed, using metric fallback: {exc}")
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
        print(f"[{CARD.name}] LLM respond failed, using metric fallback: {exc}")
        return fallback_messages(CARD.name, task, opinions)


app = make_agent(CARD, opinion_fn, respond_fn)
