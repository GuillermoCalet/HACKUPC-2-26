"""Shared helpers for all agent implementations."""
import json
import uuid
from datetime import datetime
from pathlib import Path

from orchestrator.a2a import Evidence, Message, Opinion

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text()


def extract_json(raw: str) -> dict:
    """Extract the first JSON object from model output.

    Local models sometimes wrap the answer in code fences or thinking tags even
    when prompted not to. The debate layer needs resilience more than elegance.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON object found in model output")


def parse_opinion(raw: str, agent_name: str, round_num: int) -> Opinion:
    """Parse LLM output into an Opinion, with a safe fallback."""
    try:
        data = extract_json(raw)
        data["agent"] = agent_name
        data["round"] = round_num
        # Coerce evidence items
        data["evidence"] = [Evidence(**e) for e in data.get("evidence", [])]
        return Opinion(**data)
    except Exception as exc:
        print(f"[{agent_name}] JSON parse error: {exc}\nRaw: {raw[:200]}")
        return Opinion(
            agent=agent_name,
            round=round_num,
            verdict="TEST_NEXT",
            confidence=0.3,
            claims=["Unable to parse response — defaulting to TEST_NEXT"],
            evidence=[],
        )


def parse_messages(raw: str, from_agent: str) -> list[Message]:
    """Parse LLM output into a list of Message objects."""
    try:
        data = extract_json(raw)
        msgs = data.get("messages", [])
        result = []
        for m in msgs:
            result.append(Message(
                id=str(uuid.uuid4()),
                from_agent=from_agent,
                to_agent=m.get("to_agent", "ALL"),
                type=m.get("type", "challenge"),
                body=m.get("body", ""),
                timestamp=datetime.utcnow(),
            ))
        return result
    except Exception as exc:
        print(f"[{from_agent}] message parse error: {exc}")
        return []


def context_str(context: dict) -> str:
    return json.dumps(
        {k: v for k, v in context.items() if k != "image_path"},
        indent=2,
        default=str,
    )


def challenges_str(prior_messages: list[Message]) -> str:
    if not prior_messages:
        return "(none)"
    return "\n".join(f"- From {m.from_agent}: {m.body}" for m in prior_messages)


def opinions_str(opinions: list[Opinion]) -> str:
    return json.dumps([o.model_dump(mode="json") for o in opinions], indent=2)
