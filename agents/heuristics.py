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
        # ctr_slope_7d is stored as a rate, so -0.001 means roughly -0.10
        # percentage points/day. The previous -0.05 threshold made lifetime
        # decay carry too much of the fatigue decision and hid useful winners.
        or _metric(context, "ctr_slope_7d", default=0.0) <= -0.001
    )


def _low_sample(context: dict[str, Any]) -> bool:
    installs = _metric(context, "installs", "conversions", "total_conversions", default=0.0)
    impressions = _metric(context, "impressions", "total_impressions", default=0.0)
    return installs < 50 or impressions < 1000


def _roas(context: dict[str, Any]) -> float:
    return _metric(context, "overall_roas", "roas", default=0.0)


def _confirmed_fatigue(context: dict[str, Any]) -> bool:
    status = _text(context, "creative_status", default="").lower()
    fatigue_day = _metric(context, "fatigue_day", default=0.0)
    return "fatigue" in status or fatigue_day > 0


def _useful_performance_signal(context: dict[str, Any]) -> bool:
    status = _text(context, "creative_status", default="").lower()
    return (
        "top_performer" in status
        or _metric(context, "ctr_pct", default=0.5) >= 0.65
        or _metric(context, "ipm_pct", default=0.5) >= 0.65
        or _roas(context) >= 1.15
    )


def _scale_ready_signal(context: dict[str, Any]) -> bool:
    """Strong enough business/performance signal that non-blocking agents can SCALE."""

    if _low_sample(context) or _confirmed_fatigue(context):
        return False
    status = _text(context, "creative_status", default="").lower()
    ctr_pct = _metric(context, "ctr_pct", default=0.5)
    ipm_pct = _metric(context, "ipm_pct", default=0.5)
    cvr_pct = _metric(context, "cvr_pct", default=0.5)
    spend_pct = _metric(context, "spend_pct", "spend_share_pct", default=0.5)
    roas = _roas(context)
    top_performer = "top_performer" in status
    strong_metrics = ctr_pct >= 0.75 and ipm_pct >= 0.75 and cvr_pct >= 0.45
    efficient_spend = roas >= 1.20 and spend_pct <= 0.70
    return efficient_spend and (top_performer or strong_metrics)


def _pause_harm_is_clear(context: dict[str, Any]) -> bool:
    spend_pct = _metric(context, "spend_pct", "spend_share_pct", default=0.5)
    ctr_pct = _metric(context, "ctr_pct", default=0.5)
    ipm_pct = _metric(context, "ipm_pct", default=0.5)
    roas = _roas(context)
    losing_at_scale = bool(roas) and roas < 0.80 and spend_pct >= 0.50
    wasteful_with_fatigue = (
        _confirmed_fatigue(context)
        and spend_pct >= 0.75
        and ctr_pct <= 0.25
        and ipm_pct <= 0.25
        and (not roas or roas < 1.10)
    )
    return losing_at_scale or wasteful_with_fatigue


def _strong_recent_decay(context: dict[str, Any]) -> bool:
    return _metric(context, "ctr_slope_7d", default=0.0) <= -0.001


def _financial_pivot_is_clear(context: dict[str, Any]) -> bool:
    spend_pct = _metric(context, "spend_pct", "spend_share_pct", default=0.5)
    ctr_pct = _metric(context, "ctr_pct", default=0.5)
    ipm_pct = _metric(context, "ipm_pct", default=0.5)
    roas = _roas(context)
    return (
        roas < 1.10
        or (spend_pct >= 0.75 and (ctr_pct < 0.35 or ipm_pct < 0.35) and roas < 1.20)
    )


def _has_grounded_execution_issue(opinion: Opinion) -> bool:
    has_visual_evidence = any(evidence.type == "visual" for evidence in opinion.evidence)
    text = " ".join(opinion.claims).lower()
    issue_terms = (
        "cta",
        "call-to-action",
        "button",
        "layout",
        "clutter",
        "text",
        "headline",
        "first frame",
        "hook",
        "dominant",
        "visual hierarchy",
        "legible",
        "readable",
    )
    return has_visual_evidence and any(term in text for term in issue_terms)


def _supports_visual_pause(opinion: Opinion) -> bool:
    text = " ".join(opinion.claims).lower()
    hard_blockers = (
        "missing cta",
        "no visible cta",
        "invisible cta",
        "illegible",
        "unreadable",
        "cannot read",
        "visually incoherent",
        "actively creating rejection",
        "distrust",
    )
    return any(blocker in text for blocker in hard_blockers)


def calibrate_opinion(
    agent_name: str,
    task: Task,
    opinion: Opinion,
    previous_opinion: Opinion | None = None,
) -> Opinion:
    """Apply agent-local decision calibration without changing the A2A flow.

    These guardrails keep each agent inside its stated remit: PAUSE should mean
    clear active harm, while uncertainty or a tired-but-useful concept should
    become TEST_NEXT or PIVOT.
    """

    context = task.context
    updates: dict[str, Any] = {}

    if agent_name == "fatigue_detective" and opinion.verdict == "PAUSE":
        if not _pause_harm_is_clear(context):
            next_verdict: Verdict = "PIVOT" if _confirmed_fatigue(context) and _useful_performance_signal(context) else "TEST_NEXT"
            updates = {
                "verdict": next_verdict,
                "confidence": min(opinion.confidence, 0.74),
                "claims": [
                    "Fatigue does not justify a full pause here; without clear waste or confirmed fatigue, the safer recommendation is a controlled next decision rather than killing the creative.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name == "fatigue_detective" and opinion.verdict == "PIVOT":
        if _scale_ready_signal(context):
            updates = {
                "verdict": "SCALE",
                "confidence": min(max(opinion.confidence, 0.68), 0.76),
                "claims": [
                    "Fatigue does not block scale: this is a profitable top performer with no confirmed fatigue flag, so the right fatigue stance is scale with monitoring.",
                    *opinion.claims[:2],
                ],
            }
        elif not _confirmed_fatigue(context) and not _strong_recent_decay(context):
            updates = {
                "verdict": "TEST_NEXT",
                "confidence": min(opinion.confidence, 0.66),
                "claims": [
                    "Fatigue matters, but it is not confirmed here; lifetime decay alone should trigger a controlled next test rather than a forced creative pivot.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name == "performance_analyst" and opinion.verdict == "PAUSE":
        if not _pause_harm_is_clear(context):
            if _scale_ready_signal(context):
                next_verdict = "SCALE"
            else:
                next_verdict = "PIVOT" if _confirmed_fatigue(context) and _useful_performance_signal(context) else "TEST_NEXT"
            updates = {
                "verdict": next_verdict,
                "confidence": min(opinion.confidence, 0.70),
                "claims": [
                    "The performance read does not show clear budget harm, so PAUSE is too severe; use a measured next test unless fatigue is confirmed.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name == "risk_officer" and opinion.verdict == "PAUSE":
        if not _pause_harm_is_clear(context):
            next_verdict = "TEST_NEXT" if _low_sample(context) else "PIVOT"
            updates = {
                "verdict": next_verdict,
                "confidence": min(opinion.confidence, 0.72),
                "claims": [
                    "Financial risk does not justify a full pause because this creative is not clearly losing money at scale; reduce risk with a controlled next test or refreshed execution instead.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name == "risk_officer" and opinion.verdict in {"PIVOT", "TEST_NEXT"}:
        if _scale_ready_signal(context):
            updates = {
                "verdict": "SCALE",
                "confidence": min(max(opinion.confidence, 0.74), 0.82),
                "claims": [
                    "Risk does not block scale: return is above break-even, spend concentration is not excessive, and volume is sufficient.",
                    *opinion.claims[:2],
                ],
            }
        elif opinion.verdict == "PIVOT" and not _financial_pivot_is_clear(context):
            updates = {
                "verdict": "TEST_NEXT",
                "confidence": min(opinion.confidence, 0.66),
                "claims": [
                    "Risk is not clear enough for a pivot; the economics are not actively bad, so this should stay as a measured next test.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name in {"visual_critic", "audience_simulator"} and opinion.verdict == "PAUSE":
        if not _supports_visual_pause(opinion):
            updates = {
                "verdict": "PIVOT",
                "confidence": min(opinion.confidence, 0.68),
                "claims": [
                    "The visual or audience concern points to a specific execution change, but it is not a hard reason to stop the concept entirely.",
                    *opinion.claims[:2],
                ],
            }

    elif agent_name in {"visual_critic", "audience_simulator"} and opinion.verdict == "PIVOT":
        if not _confirmed_fatigue(context) and not _has_grounded_execution_issue(opinion):
            updates = {
                "verdict": "TEST_NEXT",
                "confidence": min(opinion.confidence, 0.64),
                "claims": [
                    "The execution issue is not grounded enough to force a pivot, so the next step should be a controlled test.",
                    *opinion.claims[:2],
                ],
            }

    if not updates:
        return opinion

    changed_from = opinion.changed_from
    new_verdict = updates.get("verdict")
    if previous_opinion and new_verdict and previous_opinion.verdict != new_verdict:
        changed_from = previous_opinion.verdict
    return opinion.model_copy(update={**updates, "changed_from": changed_from})


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
    confirmed_fatigue = _confirmed_fatigue(context)
    low_sample = _low_sample(context)
    roas = _roas(context)

    if agent_name == "performance_analyst":
        if ctr_pct >= 0.70 and ipm_pct >= 0.60 and not confirmed_fatigue and not low_sample:
            verdict: Verdict = "SCALE"
            confidence = 0.78
            claims = [
                "CTR and IPM sit above campaign peers, so the creative is producing strong top-of-funnel signal.",
                "There is enough delivery volume to consider increasing spend cautiously.",
            ]
        elif confirmed_fatigue and _useful_performance_signal(context):
            verdict = "PIVOT"
            confidence = 0.72
            claims = [
                "The creative has useful performance history, but confirmed fatigue means the current execution should be refreshed before more spend.",
                "Keep the working hook and test a new opening or call-to-action treatment.",
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
        if _metric(context, "active_days", default=0.0) < 7:
            verdict = "TEST_NEXT"
            confidence = 0.62
            claims = ["The creative is too young to judge fatigue reliably."]
        elif _scale_ready_signal(context):
            verdict = "SCALE"
            confidence = 0.70
            claims = [
                "There is no confirmed fatigue flag and the creative is strong enough that fatigue does not block controlled scale.",
                "Scale should still be monitored because lifetime click interest has declined from launch.",
            ]
        elif fatigue and _pause_harm_is_clear(context):
            verdict = "PAUSE"
            confidence = 0.82
            claims = [
                "Fatigue is paired with weak efficiency or poor return, so continuing this exact asset risks wasting spend.",
                "Pause this execution until the creative is refreshed or budget is moved to healthier assets.",
            ]
        elif confirmed_fatigue:
            verdict = "PIVOT"
            confidence = 0.74 if _useful_performance_signal(context) else 0.66
            claims = [
                "Recent attention has decayed, but the creative still has useful performance history, so refresh the execution instead of killing the concept.",
                "The next version should keep the proven hook while changing the opening or call-to-action treatment.",
            ]
        elif fatigue:
            verdict = "TEST_NEXT"
            confidence = 0.62
            claims = [
                "Lifetime click interest has dropped, but there is no confirmed fatigue label; validate the trend before forcing a creative pivot.",
            ]
        else:
            if _useful_performance_signal(context) and not low_sample:
                verdict = "SCALE"
                confidence = 0.70
                claims = ["No confirmed fatigue block appears, and performance is strong enough to support careful scale."]
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
        elif roas >= 1.20 and spend_pct < 0.70:
            verdict = "SCALE"
            confidence = 0.76
            claims = [
                "Return is comfortably above break-even while spend concentration is not excessive.",
                "Financial risk does not block a controlled scale-up.",
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
            claims = [
                "Return is not clearly bad and sample size is usable, but risk evidence is not strong enough to justify broad scale."
            ]
        evidence = [
            _evidence("metric", "installs", installs),
            _evidence("metric", "spend_pct", spend_pct),
            _evidence("metric", "overall_roas", roas),
        ]

    elif agent_name == "visual_critic":
        format_ = _text(context, "format")
        theme = _text(context, "theme", "primary_theme")
        if confirmed_fatigue:
            verdict = "PIVOT"
            confidence = 0.66
            claims = [
                "The creative likely needs a refreshed visual hook because attention is decaying.",
                "Keep the core offer but change the presentation before another push.",
            ]
        elif ctr_pct >= 0.75 and ipm_pct >= 0.65:
            verdict = "SCALE"
            confidence = 0.66
            claims = [
                "The creative metadata and campaign response suggest the visual concept is clear enough to keep investing.",
                "No confirmed visual or fatigue blocker appears in the structured data.",
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
        if ctr_pct >= 0.70 and cvr_pct >= 0.45 and not confirmed_fatigue:
            verdict = "SCALE"
            confidence = 0.66
            claims = [
                "The creative appears relevant enough to attract users and still convert them.",
                "Audience reaction is likely positive if spend is increased carefully.",
            ]
        elif confirmed_fatigue and _useful_performance_signal(context):
            verdict = "PIVOT"
            confidence = 0.66
            claims = [
                "The audience has responded before, but confirmed fatigue means the next version needs a fresher hook.",
                "Do not kill the concept; change the execution and retest it.",
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
