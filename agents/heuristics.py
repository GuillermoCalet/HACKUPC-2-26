"""Deterministic agent fallbacks for demo resilience.

These live in the agent package on purpose: if an LLM provider is unavailable,
the independent agent service still returns its own domain-specific opinion
instead of forcing the orchestrator to invent one.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

from orchestrator.a2a import Evidence, Message, Opinion, Task, Verdict


def _metric(context: dict[str, Any], *names: str, default: float = 0.0) -> float:
    for name in names:
        value = context.get(name)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return default


def _text(context: dict[str, Any], *names: str, default: str = "unknown") -> str:
    for name in names:
        value = context.get(name)
        if value not in (None, ""):
            return str(value)
    return default


def _evidence(type_: str, key: str, value: Any, source: str = "creative_features") -> Evidence:
    return Evidence(type=type_, key=key, value=value, source=source)


def _changed_from(previous_opinion: Opinion | None, verdict: Verdict) -> Verdict | None:
    if previous_opinion and previous_opinion.verdict != verdict:
        return previous_opinion.verdict
    return None


def _message(from_agent: str, to_agent: str, type_: str, body: str) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        from_agent=from_agent,
        to_agent=to_agent,
        type=type_,
        body=body,
        timestamp=datetime.now(timezone.utc),
    )


def _fatigue_signal(context: dict[str, Any]) -> bool:
    status = _text(context, "creative_status", default="").lower()
    return (
        "fatigue" in status
        or _metric(context, "ctr_decay_pct", default=0.0) <= -0.50
        or _metric(context, "ctr_slope_7d", default=0.0) <= -0.05
    )


def _low_sample(context: dict[str, Any]) -> bool:
    installs = _metric(context, "installs", "conversions", "total_conversions", default=0.0)
    impressions = _metric(context, "impressions", "total_impressions", default=0.0)
    return installs < 50 or impressions < 1000


def _roas(context: dict[str, Any]) -> float:
    return _metric(context, "overall_roas", "roas", default=0.0)


def fallback_opinion(
    agent_name: str,
    task: Task,
    prior_messages: list[Message] | None = None,
    previous_opinion: Opinion | None = None,
) -> Opinion:
    context = task.context
    round_num = 3 if prior_messages else 1
    ctr_pct = _metric(context, "ctr_pct", default=0.5)
    ipm_pct = _metric(context, "ipm_pct", default=0.5)
    cvr_pct = _metric(context, "cvr_pct", default=0.5)
    spend_pct = _metric(context, "spend_pct", "spend_share_pct", default=0.5)
    installs = _metric(context, "installs", "conversions", "total_conversions", default=0.0)
    fatigue = _fatigue_signal(context)
    low_sample = _low_sample(context)
    roas = _roas(context)

    if agent_name == "performance_analyst":
        if ctr_pct >= 0.70 and ipm_pct >= 0.60 and not fatigue and not low_sample:
            verdict: Verdict = "SCALE"
            confidence = 0.78
            claims = [
                "CTR and IPM sit above campaign peers, so the creative is producing strong top-of-funnel signal.",
                "There is enough delivery volume to consider increasing spend cautiously.",
            ]
        elif ctr_pct >= 0.70 or ipm_pct >= 0.65:
            verdict = "TEST_NEXT"
            confidence = 0.68
            claims = [
                "The creative shows useful attention or install pull, but the signal is not clean enough for scale.",
                "A controlled next test should validate whether the performance holds.",
            ]
        elif cvr_pct <= 0.30:
            verdict = "PIVOT"
            confidence = 0.70
            claims = [
                "The creative is not converting attention into installs well enough versus peers.",
                "The next version should keep learnings but change the performance hook.",
            ]
        else:
            verdict = "TEST_NEXT"
            confidence = 0.58
            claims = ["Performance is mixed, so the safest move is another controlled test."]
        evidence = [
            _evidence("metric", "ctr_pct", ctr_pct),
            _evidence("metric", "ipm_pct", ipm_pct),
            _evidence("metric", "installs", installs),
        ]

    elif agent_name == "fatigue_detective":
        if fatigue and _metric(context, "active_days", default=0.0) >= 7:
            verdict = "PAUSE"
            confidence = 0.84
            claims = [
                "Recent trend or status indicates creative fatigue, so more spend risks buying declining attention.",
                "The current asset should be paused or refreshed before any scale decision.",
            ]
        elif _metric(context, "active_days", default=0.0) < 7:
            verdict = "TEST_NEXT"
            confidence = 0.62
            claims = ["The creative is too young to judge fatigue reliably."]
        else:
            verdict = "TEST_NEXT"
            confidence = 0.60
            claims = ["No severe fatigue signal appears, but monitoring should continue before scale."]
        evidence = [
            _evidence("statistical", "ctr_decay_pct", _metric(context, "ctr_decay_pct", default=0.0)),
            _evidence("statistical", "ctr_slope_7d", _metric(context, "ctr_slope_7d", default=0.0)),
            _evidence("metric", "active_days", _metric(context, "active_days", default=0.0)),
        ]

    elif agent_name == "risk_officer":
        if low_sample:
            verdict = "TEST_NEXT"
            confidence = 0.78
            claims = [
                "Install or impression volume is below a reliable scale threshold.",
                "The decision should reduce statistical downside before increasing spend.",
            ]
        elif roas and roas < 0.80 and spend_pct >= 0.60:
            verdict = "PAUSE"
            confidence = 0.80
            claims = [
                "Spend exposure is high while return is weak, creating downside risk.",
                "The advertiser should stop pushing this creative until economics improve.",
            ]
        elif roas and roas < 1.00:
            verdict = "PIVOT"
            confidence = 0.72
            claims = ["Business return is not strong enough to justify scale; pivot the creative angle."]
        else:
            verdict = "TEST_NEXT"
            confidence = 0.64
            claims = ["Risk is acceptable for another measured test, but not decisive enough for broad scale."]
        evidence = [
            _evidence("metric", "installs", installs),
            _evidence("metric", "spend_pct", spend_pct),
            _evidence("metric", "overall_roas", roas),
        ]

    elif agent_name == "visual_critic":
        format_ = _text(context, "format")
        theme = _text(context, "theme", "primary_theme")
        if fatigue:
            verdict = "PIVOT"
            confidence = 0.66
            claims = [
                "The creative likely needs a refreshed visual hook because attention is decaying.",
                "Keep the core offer but change the presentation before another push.",
            ]
        elif ctr_pct >= 0.65:
            verdict = "TEST_NEXT"
            confidence = 0.62
            claims = [
                "The concept appears capable of getting attention, but visual quality should be validated against a challenger.",
                "A new visual variant can isolate whether the layout or hook is driving performance.",
            ]
        else:
            verdict = "PIVOT"
            confidence = 0.64
            claims = ["The current framing is not earning enough attention, so the visual angle should change."]
        evidence = [
            _evidence("categorical", "format", format_),
            _evidence("categorical", "theme", theme),
            _evidence("metric", "ctr_pct", ctr_pct),
        ]

    else:  # audience_simulator
        if ctr_pct >= 0.70 and cvr_pct >= 0.45 and not fatigue:
            verdict = "SCALE"
            confidence = 0.66
            claims = [
                "The creative appears relevant enough to attract users and still convert them.",
                "Audience reaction is likely positive if spend is increased carefully.",
            ]
        elif ctr_pct >= 0.60 and cvr_pct < 0.40:
            verdict = "PIVOT"
            confidence = 0.68
            claims = [
                "The creative can get attention, but the user promise is not persuasive enough after the click.",
                "A clearer audience-specific hook should be tested next.",
            ]
        else:
            verdict = "TEST_NEXT"
            confidence = 0.60
            claims = ["Audience response is not decisive, so another controlled test is the best next move."]
        evidence = [
            _evidence("metric", "ctr_pct", ctr_pct),
            _evidence("metric", "cvr_pct", cvr_pct),
            _evidence("categorical", "countries", _text(context, "countries")),
        ]

    return Opinion(
        agent=agent_name,
        round=round_num,
        verdict=verdict,
        confidence=confidence,
        claims=claims,
        evidence=evidence,
        changed_from=_changed_from(previous_opinion, verdict),
    )


def fallback_messages(agent_name: str, task: Task, opinions: list[Opinion]) -> list[Message]:
    context = task.context
    by_agent = {opinion.agent: opinion for opinion in opinions}
    messages: list[Message] = []

    scale_agents = [opinion for opinion in opinions if opinion.verdict == "SCALE"]
    if agent_name == "fatigue_detective" and _fatigue_signal(context):
        for opinion in scale_agents[:2]:
            messages.append(_message(
                agent_name,
                opinion.agent,
                "challenge",
                "Your SCALE vote underweights the fatigue signal. Recent decay means scale could amplify declining attention.",
            ))

    elif agent_name == "risk_officer" and (_low_sample(context) or _roas(context) < 0.8):
        for opinion in scale_agents[:2]:
            messages.append(_message(
                agent_name,
                opinion.agent,
                "evidence_request",
                "Please justify SCALE with stronger reliability evidence; sample size or return risk is still weak.",
            ))

    elif agent_name == "performance_analyst":
        fatigue_op = by_agent.get("fatigue_detective")
        if fatigue_op and fatigue_op.verdict == "PAUSE" and _metric(context, "ctr_pct", default=0.5) >= 0.75:
            messages.append(_message(
                agent_name,
                "fatigue_detective",
                "challenge",
                "The fatigue concern is valid, but top-quartile CTR suggests there may still be useful demand to retest before pausing completely.",
            ))

    elif agent_name == "visual_critic":
        risk_op = by_agent.get("risk_officer")
        if risk_op and risk_op.verdict in {"PIVOT", "TEST_NEXT"}:
            messages.append(_message(
                agent_name,
                "risk_officer",
                "concur",
                "I agree the next step should reduce risk by testing a clearer creative variant rather than scaling this exact asset.",
            ))

    elif agent_name == "audience_simulator":
        visual_op = by_agent.get("visual_critic")
        if visual_op and visual_op.verdict == "PIVOT":
            messages.append(_message(
                agent_name,
                "visual_critic",
                "concur",
                "A pivot makes sense because the audience signal suggests the hook needs to feel more relevant.",
            ))

    return messages[:2]
