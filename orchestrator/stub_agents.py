"""Deterministic local agents for end-to-end orchestrator testing.

Run all five:
    python -m orchestrator.stub_agents

Or run one by import string:
    uvicorn orchestrator.stub_agents:performance_app --port 8001
"""
from __future__ import annotations

import multiprocessing
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import uvicorn

from orchestrator.a2a import AgentCard, Evidence, Message, Opinion, Task
from orchestrator.base import make_agent


def _metric(context: dict[str, Any], name: str, default: float = 0.0) -> float:
    try:
        value = context.get(name, default)
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _evidence(type_: str, key: str, value: Any, source: str) -> Evidence:
    return Evidence(type=type_, key=key, value=value, source=source)


def _message(from_agent: str, to_agent: str, type_: str, body: str) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        from_agent=from_agent,
        to_agent=to_agent,
        type=type_,
        body=body,
        timestamp=datetime.now(timezone.utc),
    )


CARDS = {
    "performance_analyst": AgentCard(
        name="performance_analyst",
        description="Stub: analyzes top-line campaign performance metrics",
        skills=["performance", "metric"],
        endpoint="http://localhost:8001",
        vote_weight=1.0,
    ),
    "fatigue_detective": AgentCard(
        name="fatigue_detective",
        description="Stub: detects creative fatigue from recent trend columns",
        skills=["fatigue", "trend"],
        endpoint="http://localhost:8002",
        vote_weight=1.0,
    ),
    "risk_officer": AgentCard(
        name="risk_officer",
        description="Stub: checks sample size, spend, and downside risk",
        skills=["risk", "statistical"],
        endpoint="http://localhost:8003",
        vote_weight=0.8,
    ),
    "visual_critic": AgentCard(
        name="visual_critic",
        description="Stub: reviews visual clarity from metadata only",
        skills=["visual", "image"],
        endpoint="http://localhost:8004",
        vote_weight=0.7,
    ),
    "audience_simulator": AgentCard(
        name="audience_simulator",
        description="Stub: simulates audience reaction",
        skills=["audience", "creative"],
        endpoint="http://localhost:8005",
        vote_weight=0.5,
    ),
}


def _opinion_for(
    agent_name: str,
    task: Task,
    prior_messages: list[Message],
) -> Opinion:
    context = task.context
    round_num = 3 if prior_messages else 1

    if agent_name == "performance_analyst":
        if prior_messages:
            return Opinion(
                agent=agent_name,
                round=round_num,
                verdict="TEST_NEXT",
                confidence=0.72,
                claims=[
                    "Top-of-funnel metrics are strong, but the low conversion sample and fatigue challenge make immediate scale premature.",
                    "Recommendation revised after cross-examination: validate one more controlled budget step.",
                ],
                evidence=[
                    _evidence("metric", "ctr_pct", _metric(context, "ctr_pct"), "creative_features"),
                    _evidence("metric", "installs", _metric(context, "installs"), "creative_features"),
                ],
            )
        return Opinion(
            agent=agent_name,
            round=round_num,
            verdict="SCALE",
            confidence=0.82,
            claims=[
                "CTR and IPM are above campaign peers, suggesting the creative is earning attention.",
                "The performance read favors increasing spend unless risk or fatigue evidence contradicts it.",
            ],
            evidence=[
                _evidence("metric", "ctr_pct", _metric(context, "ctr_pct"), "creative_features"),
                _evidence("metric", "ipm_pct", _metric(context, "ipm_pct"), "creative_features"),
            ],
        )

    if agent_name == "fatigue_detective":
        return Opinion(
            agent=agent_name,
            round=round_num,
            verdict="PAUSE",
            confidence=0.86,
            claims=[
                "Recent CTR slope is sharply negative, which points to emerging fatigue.",
                "Scaling while decay is active risks buying lower quality impressions.",
            ],
            evidence=[
                _evidence("statistical", "ctr_slope_7d", _metric(context, "ctr_slope_7d"), "creative_features"),
                _evidence("metric", "active_days", _metric(context, "active_days"), "creative_features"),
            ],
        )

    if agent_name == "risk_officer":
        return Opinion(
            agent=agent_name,
            round=round_num,
            verdict="PIVOT",
            confidence=0.78,
            claims=[
                "Install volume is below the minimum threshold for a confident scale decision.",
                "Spend is meaningful enough that the next move should reduce downside risk.",
            ],
            evidence=[
                _evidence("metric", "installs", _metric(context, "installs"), "creative_features"),
                _evidence("metric", "spend", _metric(context, "spend"), "creative_features"),
            ],
        )

    if agent_name == "visual_critic":
        return Opinion(
            agent=agent_name,
            round=round_num,
            verdict="TEST_NEXT",
            confidence=0.62,
            claims=[
                "Metadata suggests the concept is legible, but no visual asset is required for this stub run.",
                "Creative quality should be verified against the actual image before a scale decision.",
            ],
            evidence=[
                _evidence("categorical", "format", str(context.get("format", "unknown")), "creative_features"),
                _evidence("system", "stub_mode", "metadata_only", "stub_agent"),
            ],
        )

    return Opinion(
        agent=agent_name,
        round=round_num,
        verdict="PIVOT",
        confidence=0.68,
        claims=[
            "The audience may notice the offer, but fatigue and risk signals make a new angle more attractive.",
            "A refreshed hook should be tested against the current creative.",
        ],
        evidence=[
            _evidence("categorical", "target_os", str(context.get("target_os", "unknown")), "creative_features"),
            _evidence("categorical", "countries", str(context.get("countries", "unknown")), "creative_features"),
        ],
    )


def _respond_for(agent_name: str, opinions: list[Opinion]) -> list[Message]:
    by_agent = {opinion.agent: opinion for opinion in opinions}

    if agent_name == "fatigue_detective" and "performance_analyst" in by_agent:
        return [
            _message(
                agent_name,
                "performance_analyst",
                "challenge",
                "Your SCALE vote underweights the negative recent CTR slope. Please revisit whether decay blocks scaling.",
            )
        ]

    if agent_name == "risk_officer" and "performance_analyst" in by_agent:
        return [
            _message(
                agent_name,
                "performance_analyst",
                "evidence_request",
                "Please justify SCALE despite installs being below the reliability threshold.",
            )
        ]

    if agent_name == "visual_critic" and "risk_officer" in by_agent:
        return [
            _message(
                agent_name,
                "risk_officer",
                "concur",
                "I agree that the visual read is not strong enough to offset the statistical risk.",
            )
        ]

    if agent_name == "audience_simulator" and "fatigue_detective" in by_agent:
        return [
            _message(
                agent_name,
                "fatigue_detective",
                "concur",
                "Audience reaction is likely to weaken if the same hook is already decaying.",
            )
        ]

    return []


def _make_stub(card: AgentCard):
    async def opinion_fn(
        task: Task,
        prior_messages: list[Message],
        previous_opinion: Opinion | None = None,
    ) -> Opinion:
        return _opinion_for(card.name, task, prior_messages)

    async def respond_fn(task: Task, opinions: list[Opinion]) -> list[Message]:
        return _respond_for(card.name, opinions)

    return make_agent(card, opinion_fn, respond_fn)


performance_app = _make_stub(CARDS["performance_analyst"])
fatigue_app = _make_stub(CARDS["fatigue_detective"])
risk_app = _make_stub(CARDS["risk_officer"])
visual_app = _make_stub(CARDS["visual_critic"])
audience_app = _make_stub(CARDS["audience_simulator"])


APP_SPECS = (
    ("performance_app", 8001),
    ("fatigue_app", 8002),
    ("risk_app", 8003),
    ("visual_app", 8004),
    ("audience_app", 8005),
)


def _run_one(app_name: str, port: int) -> None:
    uvicorn.run(
        f"orchestrator.stub_agents:{app_name}",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


def main() -> None:
    processes: list[multiprocessing.Process] = []
    for app_name, port in APP_SPECS:
        process = multiprocessing.Process(target=_run_one, args=(app_name, port))
        process.start()
        processes.append(process)
        time.sleep(0.15)

    print("Stub agents running on ports 8001-8005. Press Ctrl+C to stop.")
    try:
        for process in processes:
            process.join()
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()
        for process in processes:
            process.join(timeout=5)


if __name__ == "__main__":
    main()
