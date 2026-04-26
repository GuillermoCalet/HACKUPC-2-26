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


def _flatten_evidence(final_opinions: list) -> str:
    """Build a flat, readable evidence digest the synthesizer can easily scan."""
    lines = []
    for op in final_opinions:
        if not isinstance(op, dict):
            continue
        agent   = op.get("agent", "unknown")
        verdict = op.get("verdict", "?")
        conf    = op.get("confidence", 0)
        lines.append(f"\n--- {agent} | verdict={verdict} | confidence={conf:.0%} ---")
        for e in op.get("evidence", []):
            if isinstance(e, dict):
                lines.append(f"  evidence: [{e.get('type','')}] {e.get('key','')} = {e.get('value','')} (source: {e.get('source','')})")
        for c in op.get("claims", []):
            lines.append(f"  claim: {c}")
        if op.get("changed_from"):
            lines.append(f"  *** CHANGED VERDICT: {op['changed_from']} → {verdict} ***")
    return "\n".join(lines) if lines else "(no structured evidence available)"


def synthesize(
    transcript: list,
    final_opinions: list,
    context: dict,
    weighted_verdict: str,
) -> dict:
    prompt_template = PROMPT_PATH.read_text()

    # Strip image path from context (not useful for text synthesis)
    clean_context = {k: v for k, v in context.items() if k != "image_path"}

    user_msg = (
        prompt_template
        .replace("{weighted_verdict}", weighted_verdict)
        .replace("{context}", json.dumps(clean_context, indent=2, default=str))
        .replace("{transcript}", json.dumps(transcript, indent=2, default=str))
        .replace("{final_opinions}", _flatten_evidence(final_opinions))
    )

    raw = generate_text(user_msg, max_tokens=1536)

    try:
        return extract_json(raw)
    except Exception:
        verdicts = [o.get("verdict") for o in final_opinions if isinstance(o, dict)]
        from collections import Counter
        top = Counter(verdicts).most_common(1)
        verdict = top[0][0] if top else weighted_verdict

        # Plain-English fallback: pull the first readable claim from each agent
        plain_bullets: list[str] = []
        for op in final_opinions:
            if not isinstance(op, dict):
                continue
            claims = op.get("claims", [])
            if claims:
                plain_bullets.append(claims[0])
            if len(plain_bullets) >= 3:
                break

        verdict_actions = {
            "SCALE":     "Keep running this ad and consider increasing the budget — the results look good.",
            "PAUSE":     "Stop running this ad for now. Check the full transcript to see what the analysts found.",
            "PIVOT":     "This ad isn't working well enough. Make a new version with a fresh approach.",
            "TEST_NEXT": "Give this ad a bit more time and budget before making a big decision — it needs more data.",
        }

        return {
            "verdict": verdict,
            "headline": (
                "The boardroom has reached a verdict — scroll down to see the full analyst debate."
            ),
            "evidence_bullets": plain_bullets or [
                "The analysts reviewed the ad's performance, visuals, and audience fit.",
                f"{len(final_opinions)} specialists weighed in before reaching this conclusion.",
                "See the full debate transcript below for the detailed reasoning.",
            ],
            "dissent": None,
            "next_action": verdict_actions.get(
                verdict,
                "Review the full agent transcript for specific next steps.",
            ),
        }
