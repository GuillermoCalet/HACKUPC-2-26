"""
Audience Simulator agent — Port 8005.

Simulates how a realistic target audience member reacts to the creative.
Model: claude-sonnet-4-6 with vision.
"""
import base64
from pathlib import Path

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from agents._agent_helpers import (
    get_client, load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)

CARD = AgentCard(
    name="audience_simulator",
    description="Simulates target audience reaction to the creative from a user perspective",
    skills=["simulate_audience", "respond_to_challenge"],
    endpoint="http://localhost:8005",
    vote_weight=0.5,
)

MODEL = "claude-sonnet-4-6"


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


async def opinion_fn(task: Task, prior_messages: list[Message]) -> Opinion:
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

    image_b64 = _load_image_b64(task.image_path)
    if image_b64:
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
            },
            {"type": "text", "text": user_text},
        ]
    else:
        content = user_text + "\n(Image unavailable — base analysis on metadata only)"

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
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
