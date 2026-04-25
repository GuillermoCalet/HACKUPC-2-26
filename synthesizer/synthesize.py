"""
Final verdict synthesizer.

Receives the full debate transcript + weighted vote result and produces
the marketer-facing verdict card.
"""
import json
from pathlib import Path

from agents._agent_helpers import extract_json
from agents.llm_client import generate_text

PROMPT_PATH = Path(__file__).parent.parent / "agents" / "prompts" / "synthesizer.txt"


def synthesize(
    transcript: list,
    final_opinions: list,
    context: dict,
    weighted_verdict: str,
) -> dict:
    prompt_template = PROMPT_PATH.read_text()
    user_msg = (
        prompt_template
        .replace("{weighted_verdict}", weighted_verdict)
        .replace("{context}", json.dumps(
            {k: v for k, v in context.items() if k != "image_path"},
            indent=2, default=str,
        ))
        .replace("{transcript}", json.dumps(transcript, indent=2, default=str))
        .replace("{final_opinions}", json.dumps(final_opinions, indent=2, default=str))
    )

    raw = generate_text(user_msg, max_tokens=1024)

    try:
        return extract_json(raw)
    except Exception:
        verdicts = [o.get("verdict") for o in final_opinions if isinstance(o, dict)]
        from collections import Counter
        top = Counter(verdicts).most_common(1)
        verdict = top[0][0] if top else weighted_verdict
        return {
            "verdict": verdict,
            "headline": f"Boardroom reached {verdict} based on {len(final_opinions)} agent opinions.",
            "evidence_bullets": [
                f"Weighted vote: {weighted_verdict}",
                f"{len(final_opinions)} agents participated in the debate.",
                "See transcript for full details.",
            ],
            "dissent": None,
            "next_action": "Review the full agent transcript for detailed reasoning.",
        }
