"""
Audience Simulator agent — Port 8005.

Simulates how a realistic target audience member reacts to the creative.
Model: configured by LLM_PROVIDER / OLLAMA_MODEL_VISION.
"""
import base64
from pathlib import Path

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents.llm_client import generate_text, generate_vision
from agents._agent_helpers import (
    load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)
from agents.heuristics import fallback_messages, fallback_opinion

CARD = AgentCard(
    name="audience_simulator",
    description="Simulates target audience reaction to the creative from a user perspective",
    skills=["simulate_audience", "respond_to_challenge"],
    endpoint="http://localhost:8005",
    vote_weight=0.5,
)

def _build_persona(context: dict) -> str:
    return (
        f"You are a mobile user in {context.get('countries', 'an unknown country')} "
        f"using {context.get('target_os', 'a mobile device')}.\n"
        f"You engage with {context.get('vertical', 'general')} apps. "
        f"You are aged {context.get('target_age_segment', 'unknown')}. "
        f"You are scrolling a social feed."
    )


def _load_image_b64(image_path: str) -> str | None:
    try:
        return base64.b64encode(Path(image_path).read_bytes()).decode()
    except Exception as exc:
        print(f"[audience_simulator] Could not load image {image_path}: {exc}")
        return None


async def opinion_fn(
    task: Task,
    prior_messages: list[Message],
    previous_opinion: Opinion | None = None,
) -> Opinion:
    round_num = 3 if prior_messages else 1
    context = task.context
    persona = _build_persona(context)

    prompt = load_prompt("audience")
    user_text = (
        prompt
        .replace("{persona}", persona)
        .replace("{context}", context_str(context))
        .replace("{target_age_segment}", str(context.get("target_age_segment", "unknown")))
        .replace("{target_os}", str(context.get("target_os", "mobile")))
        .replace("{countries}", str(context.get("countries", "unknown")))
        .replace("{challenges}", challenges_str(prior_messages))
    )

    try:
        image_b64 = _load_image_b64(task.image_path)
        if image_b64:
            raw = generate_vision(user_text, image_b64, max_tokens=1024)
        else:
            raw = generate_text(
                user_text + "\n(Image unavailable — base analysis on metadata only)",
                max_tokens=1024,
            )
        return parse_opinion(raw, CARD.name, round_num)
    except Exception as exc:
        print(f"[{CARD.name}] LLM opinion failed, using audience fallback: {exc}")
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
        print(f"[{CARD.name}] LLM respond failed, using audience fallback: {exc}")
        return fallback_messages(CARD.name, task, opinions)


app = make_agent(CARD, opinion_fn, respond_fn)
