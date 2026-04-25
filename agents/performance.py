"""
Performance Analyst agent — Port 8001.

Quantifies how a creative performs relative to campaign peers on hard metrics.
Model: claude-haiku-4-5-20251001
"""
from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents._agent_helpers import (
    get_client, load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)

CARD = AgentCard(
    name="performance_analyst",
    description="Quantifies creative performance relative to campaign peers on hard metrics",
    skills=["analyze_performance", "respond_to_challenge"],
    endpoint="http://localhost:8001",
    vote_weight=1.0,
)

MODEL = "claude-haiku-4-5-20251001"


async def opinion_fn(task: Task, prior_messages: list[Message]) -> Opinion:
    round_num = 3 if prior_messages else 1
    prompt = load_prompt("performance")
    user_msg = (
        prompt
        .replace("{context}", context_str(task.context))
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
