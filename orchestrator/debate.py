import asyncio
import uuid
from collections import defaultdict

import httpx

from orchestrator.a2a import Task, Opinion, Message, OpinionRequest, RespondRequest

AGENT_ENDPOINTS: dict[str, str] = {
    "performance_analyst": "http://localhost:8001",
    "fatigue_detective": "http://localhost:8002",
    "risk_officer": "http://localhost:8003",
    "visual_critic": "http://localhost:8004",
    "audience_simulator": "http://localhost:8005",
}

AGENT_WEIGHTS: dict[str, float] = {
    "performance_analyst": 1.0,
    "fatigue_detective": 1.0,
    "risk_officer": 0.8,
    "visual_critic": 0.7,
    "audience_simulator": 0.5,
}


async def _post_opinion(client: httpx.AsyncClient, ep: str, task: Task, prior_messages: list[Message]) -> Opinion | None:
    try:
        req = OpinionRequest(task=task, prior_messages=prior_messages)
        r = await client.post(f"{ep}/opinion", json=req.model_dump(mode="json"), timeout=45)
        r.raise_for_status()
        return Opinion(**r.json())
    except Exception as exc:
        print(f"[debate] opinion error at {ep}: {exc}")
        return None


async def _post_respond(client: httpx.AsyncClient, ep: str, task: Task, opinions: list[Opinion]) -> list[Message]:
    try:
        req = RespondRequest(task=task, opinions=opinions)
        r = await client.post(f"{ep}/respond", json=req.model_dump(mode="json"), timeout=45)
        r.raise_for_status()
        return [Message(**m) for m in r.json()]
    except Exception as exc:
        print(f"[debate] respond error at {ep}: {exc}")
        return []


def compute_weighted_vote(final_opinions: list[Opinion]) -> str:
    scores: dict[str, float] = defaultdict(float)
    for op in final_opinions:
        weight = AGENT_WEIGHTS.get(op.agent, 0.5)
        scores[op.verdict] += weight * op.confidence
    return max(scores, key=scores.get) if scores else "TEST_NEXT"


def apply_safety_overrides(verdict: str, context: dict, final_opinions: list[Opinion]) -> str:
    if context.get("installs", 0) < 50 and verdict == "SCALE":
        return "TEST_NEXT"

    fatigue_op = next((o for o in final_opinions if o.agent == "fatigue_detective"), None)
    if fatigue_op and fatigue_op.verdict == "PAUSE" and fatigue_op.confidence > 0.8:
        if verdict == "SCALE":
            return "PAUSE"

    risk_op = next((o for o in final_opinions if o.agent == "risk_officer"), None)
    if risk_op and risk_op.confidence > 0.7 and risk_op.verdict in ("PAUSE", "PIVOT"):
        if verdict == "SCALE":
            return "PIVOT"

    return verdict


async def run_debate(task: Task) -> dict:
    transcript = []

    async with httpx.AsyncClient(timeout=60) as client:
        # Round 1 — parallel independent opinions
        r1_results = await asyncio.gather(*[
            _post_opinion(client, ep, task, [])
            for ep in AGENT_ENDPOINTS.values()
        ])
        opinions_r1 = [op for op in r1_results if op is not None]
        transcript.append({"round": 1, "type": "opinions", "data": [o.model_dump(mode="json") for o in opinions_r1]})

        if not opinions_r1:
            return {"transcript": transcript, "final_opinions": [], "weighted_verdict": "TEST_NEXT"}

        # Round 2 — cross-examination (each agent sees all R1 opinions)
        r2_results = await asyncio.gather(*[
            _post_respond(client, ep, task, opinions_r1)
            for ep in AGENT_ENDPOINTS.values()
        ])
        challenges: list[Message] = [msg for msgs in r2_results for msg in msgs]
        transcript.append({"round": 2, "type": "challenges", "data": [m.model_dump(mode="json") for m in challenges]})

        # Round 3 — only challenged agents revise
        challenged_agents = {m.to_agent for m in challenges if m.type in ("challenge", "evidence_request")}
        agent_ep_map = {name: ep for name, ep in AGENT_ENDPOINTS.items()}

        r3_calls = []
        for agent_name in challenged_agents:
            ep = agent_ep_map.get(agent_name)
            if ep is None:
                continue
            my_challenges = [m for m in challenges if m.to_agent == agent_name]
            r3_calls.append(_post_opinion(client, ep, task, my_challenges))

        r3_results = await asyncio.gather(*r3_calls)
        revisions = [op for op in r3_results if op is not None]
        transcript.append({"round": 3, "type": "revisions", "data": [o.model_dump(mode="json") for o in revisions]})

    # Merge: revised opinion overrides Round 1
    final_by_agent: dict[str, Opinion] = {o.agent: o for o in opinions_r1}
    for rev in revisions:
        original = final_by_agent.get(rev.agent)
        if original and rev.verdict != original.verdict:
            rev.changed_from = original.verdict
        final_by_agent[rev.agent] = rev

    final_opinions = list(final_by_agent.values())

    weighted_verdict = compute_weighted_vote(final_opinions)
    safe_verdict = apply_safety_overrides(weighted_verdict, task.context, final_opinions)

    return {
        "transcript": transcript,
        "final_opinions": [o.model_dump(mode="json") for o in final_opinions],
        "weighted_verdict": safe_verdict,
    }
