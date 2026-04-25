"""
Visual Critic agent — Port 8004.

Analyzes the ad image for quality, CTA clarity, and format fit.
Model: configured by LLM_PROVIDER / OLLAMA_MODEL_VISION.
Caches vision results in evidence.db to avoid re-calling the API.
"""
import base64
import json
from pathlib import Path

from orchestrator.a2a import AgentCard, Task, Opinion, Message
from orchestrator.base import make_agent
from orchestrator.evidence_store import get_vision_cache, set_vision_cache
from agents.llm_client import generate_text, generate_vision
from agents._agent_helpers import (
    load_prompt, parse_opinion, parse_messages,
    context_str, challenges_str, opinions_str,
)

CARD = AgentCard(
    name="visual_critic",
    description="Analyses the creative asset for visual quality, CTA clarity, and format suitability",
    skills=["analyze_visuals", "respond_to_challenge"],
    endpoint="http://localhost:8004",
    vote_weight=0.7,
)

def _load_image_b64(image_path: str) -> str | None:
    try:
        return base64.b64encode(Path(image_path).read_bytes()).decode()
    except Exception as exc:
        print(f"[visual_critic] Could not load image {image_path}: {exc}")
        return None


async def opinion_fn(task: Task, prior_messages: list[Message]) -> Opinion:
    round_num = 3 if prior_messages else 1
    creative_id = task.creative_id

    # Try vision cache first (skip vision API on R3 if already cached)
    cached = get_vision_cache(creative_id)

    prompt = load_prompt("visual")
    context = task.context
    user_text = (
        prompt
        .replace("{context}", context_str(context))
        .replace("{format}", str(context.get("format", "unknown")))
        .replace("{emotional_tone}", str(context.get("emotional_tone", "unknown")))
        .replace("{challenges}", challenges_str(prior_messages))
    )

    if cached and round_num == 3:
        # R3 revision: include cached analysis + challenges, no new image call
        user_text += f"\n\n== CACHED VISUAL ANALYSIS (from Round 1) ==\n{json.dumps(cached, indent=2)}"
        raw = generate_text(user_text, max_tokens=1024)
    else:
        image_b64 = _load_image_b64(task.image_path)
        if image_b64:
            raw = generate_vision(user_text, image_b64, max_tokens=1024)
        else:
            raw = generate_text(
                user_text + "\n(Image unavailable — base analysis on metadata only)",
                max_tokens=1024,
            )

        # Cache the raw response for reuse in R3
        if image_b64:
            set_vision_cache(creative_id, {"raw": raw})

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
