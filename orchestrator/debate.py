"""Debate runner for the Creative Boardroom orchestrator.

The orchestrator is intentionally not a marketing brain. It discovers agents,
moves messages between them, records the transcript, and calculates the final
weighted consensus from agent-owned opinions.
"""
from __future__ import annotations

import asyncio
import math
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx
import pandas as pd

from orchestrator import evidence_store
from orchestrator.a2a import (
    AgentCard,
    ConsensusResult,
    DebateResult,
    Evidence,
    Message,
    Opinion,
    OpinionRequest,
    RespondRequest,
    Task,
    Verdict,
)


VERDICTS: tuple[Verdict, ...] = ("SCALE", "PAUSE", "PIVOT", "TEST_NEXT")
DEFAULT_PARQUET_PATH = Path(os.getenv("PARQUET_PATH", "pipeline/creative_features.parquet"))
DEFAULT_AGENT_URLS = (
    "http://localhost:8001",
    "http://localhost:8002",
    "http://localhost:8003",
    "http://localhost:8004",
    "http://localhost:8005",
)


class CreativeNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class DebateConfig:
    agent_urls: tuple[str, ...]
    discovery_timeout_seconds: float
    data_agent_timeout_seconds: float
    vision_agent_timeout_seconds: float
    default_agent_timeout_seconds: float


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _agent_urls_from_env() -> tuple[str, ...]:
    raw = os.getenv("ORCHESTRATOR_AGENT_URLS") or os.getenv("AGENT_URLS")
    if not raw:
        return DEFAULT_AGENT_URLS
    urls = tuple(url.strip().rstrip("/") for url in raw.split(",") if url.strip())
    return urls or DEFAULT_AGENT_URLS


def default_config() -> DebateConfig:
    return DebateConfig(
        agent_urls=_agent_urls_from_env(),
        discovery_timeout_seconds=_env_float("AGENT_DISCOVERY_TIMEOUT_SECONDS", 3.0),
        data_agent_timeout_seconds=_env_float("AGENT_DATA_TIMEOUT_SECONDS", 30.0),
        vision_agent_timeout_seconds=_env_float("AGENT_VISION_TIMEOUT_SECONDS", 90.0),
        default_agent_timeout_seconds=_env_float("AGENT_TIMEOUT_SECONDS", 45.0),
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return False


def json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe builtins."""

    if _is_missing(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return value


def fake_creative_context(creative_id: str = "demo_creative") -> dict[str, Any]:
    """Fallback row for local demos before pipeline/creative_features.parquet exists."""

    return {
        "creative_id": str(creative_id),
        "campaign_id": "demo_campaign",
        "image_path": None,
        "format": "static_image",
        "theme": "limited_time_offer",
        "language": "en",
        "impressions": 12000,
        "clicks": 480,
        "installs": 42,
        "conversions": 42,
        "spend": 850.0,
        "ctr": 0.04,
        "cvr": 0.0875,
        "ipm": 3.5,
        "cpi": 20.24,
        "roas": 0.65,
        "ctr_pct": 0.91,
        "ipm_pct": 0.82,
        "cvr_pct": 0.35,
        "spend_pct": 0.78,
        "ctr_slope_7d": -0.12,
        "active_days": 14,
        "creative_status": "demo_low_sample_high_ctr_fatigue_risk",
        "target_os": "iOS",
        "countries": "US, ES",
        "objective": "mobile_app_installs",
        "target_age_segment": "25-44",
    }


def load_creative_rows(parquet_path: Path | str = DEFAULT_PARQUET_PATH) -> list[dict[str, Any]]:
    path = Path(parquet_path)
    if not path.exists():
        return [fake_creative_context()]

    df = pd.read_parquet(path)
    if "creative_id" not in df.columns:
        raise ValueError(f"{path} must contain a creative_id column")
    return [json_safe(row) for row in df.to_dict(orient="records")]


def load_creative_context(
    creative_id: str,
    parquet_path: Path | str = DEFAULT_PARQUET_PATH,
) -> dict[str, Any]:
    path = Path(parquet_path)
    if not path.exists():
        context = fake_creative_context(creative_id)
        return json_safe(context)

    df = pd.read_parquet(path)
    if "creative_id" not in df.columns:
        raise ValueError(f"{path} must contain a creative_id column")

    ids = df["creative_id"].astype(str)
    row = df[ids == str(creative_id)]
    if row.empty:
        raise CreativeNotFoundError(f"Creative {creative_id} not found in {path}")

    return json_safe(row.iloc[0].to_dict())


def build_task(
    creative_id: str,
    parquet_path: Path | str = DEFAULT_PARQUET_PATH,
    campaign_id: str | None = None,
) -> Task:
    context = load_creative_context(creative_id, parquet_path)
    task_campaign_id = str(context.get("campaign_id") or campaign_id or "demo_campaign")
    image_path = context.get("image_path") or None
    return Task(
        task_id=str(uuid.uuid4()),
        creative_id=str(creative_id),
        campaign_id=task_campaign_id,
        context=context,
        image_path=str(image_path) if image_path else None,
    )


async def _fetch_agent_card(
    client: httpx.AsyncClient,
    url: str,
    config: DebateConfig,
) -> AgentCard:
    endpoint = url.rstrip("/")
    response = await client.get(
        f"{endpoint}/.well-known/agent.json",
        timeout=config.discovery_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    data.setdefault("endpoint", endpoint)
    if not data["endpoint"]:
        data["endpoint"] = endpoint
    return AgentCard.model_validate(data)


async def discover_agents(
    agent_urls: Sequence[str] | None = None,
    config: DebateConfig | None = None,
) -> list[AgentCard]:
    """Discover live agent cards from configured base URLs."""

    cfg = config or default_config()
    urls = tuple(url.rstrip("/") for url in (agent_urls or cfg.agent_urls))
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(_fetch_agent_card(client, url, cfg) for url in urls),
            return_exceptions=True,
        )

    cards: list[AgentCard] = []
    seen: set[str] = set()
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            print(f"[orchestrator] Agent discovery failed for {url}: {result}")
            continue
        if result.name in seen:
            print(f"[orchestrator] Duplicate agent name ignored: {result.name}")
            continue
        cards.append(result)
        seen.add(result.name)
    return cards


def _timeout_for_agent(card: AgentCard, config: DebateConfig) -> float:
    searchable = " ".join([card.name, card.description, *card.skills]).lower()
    if any(token in searchable for token in ("vision", "visual", "image", "audience")):
        return config.vision_agent_timeout_seconds
    if any(token in searchable for token in ("performance", "risk", "fatigue", "metric", "statistical")):
        return config.data_agent_timeout_seconds
    return config.default_agent_timeout_seconds


def _system_error_evidence(error: Exception | str) -> Evidence:
    return Evidence(
        type="system",
        key="agent_error",
        value=str(error),
        source="orchestrator",
    )


def _fallback_opinion(
    card: AgentCard,
    round_: int,
    error: Exception | str,
    previous_opinion: Opinion | None = None,
) -> Opinion:
    changed_from = None
    if previous_opinion is not None and previous_opinion.verdict != "TEST_NEXT":
        changed_from = previous_opinion.verdict
    return Opinion(
        agent=card.name,
        round=round_,
        verdict="TEST_NEXT",
        confidence=0.25,
        claims=[
            "Agent call failed; orchestrator substituted a conservative TEST_NEXT fallback.",
        ],
        evidence=[_system_error_evidence(error)],
        changed_from=changed_from,
    )


async def _post_opinion(
    client: httpx.AsyncClient,
    card: AgentCard,
    task: Task,
    round_: int,
    config: DebateConfig,
    prior_messages: list[Message] | None = None,
    previous_opinion: Opinion | None = None,
) -> Opinion:
    request = OpinionRequest(
        task=task,
        prior_messages=prior_messages or [],
        previous_opinion=previous_opinion,
    )
    response = await client.post(
        f"{card.endpoint}/opinion",
        json=request.model_dump(mode="json"),
        timeout=_timeout_for_agent(card, config),
    )
    response.raise_for_status()
    opinion = Opinion.model_validate(response.json())
    return opinion.model_copy(update={"agent": card.name, "round": round_})


def _message_from_payload(card: AgentCard, payload: dict[str, Any]) -> Message:
    data = dict(payload)
    data.setdefault("id", str(uuid.uuid4()))
    data.setdefault("from_agent", card.name)
    data.setdefault("to_agent", "ALL")
    data.setdefault("timestamp", datetime.now(timezone.utc))
    message = Message.model_validate(data)
    return message.model_copy(update={"from_agent": card.name})


async def _post_respond(
    client: httpx.AsyncClient,
    card: AgentCard,
    task: Task,
    opinions: list[Opinion],
    config: DebateConfig,
) -> list[Message]:
    request = RespondRequest(task=task, opinions=opinions)
    response = await client.post(
        f"{card.endpoint}/respond",
        json=request.model_dump(mode="json"),
        timeout=_timeout_for_agent(card, config),
    )
    response.raise_for_status()
    raw_messages = response.json() or []
    if not isinstance(raw_messages, list):
        raise ValueError("/respond must return a JSON list of Message objects")
    return [_message_from_payload(card, item) for item in raw_messages[:2]]


def _numeric(context: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = context.get(name)
        if _is_missing(value) or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _has_too_little_data(context: dict[str, Any]) -> bool:
    conversions = _numeric(context, "installs", "conversions", "total_conversions")
    impressions = _numeric(context, "impressions", "total_impressions")
    spend = _numeric(context, "spend", "total_spend_usd", "spend_usd")

    if conversions is not None and conversions < 50:
        return True
    if impressions is not None and impressions < 1000:
        return True
    if spend is not None and spend < 50:
        return True
    return False


def _select_without_scale(scores: dict[str, float]) -> Verdict:
    candidates = {verdict: score for verdict, score in scores.items() if verdict != "SCALE"}
    if not candidates:
        return "TEST_NEXT"
    return max(candidates, key=candidates.get)  # type: ignore[return-value]


def compute_consensus(
    final_opinions: list[Opinion],
    agents: list[AgentCard],
    context: dict[str, Any],
) -> ConsensusResult:
    scores: dict[str, float] = {verdict: 0.0 for verdict in VERDICTS}
    weights = {agent.name: agent.vote_weight for agent in agents}

    for opinion in final_opinions:
        weight = weights.get(opinion.agent, 0.5)
        scores[opinion.verdict] += weight * opinion.confidence

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_verdict = ranked[0][0] if ranked else "TEST_NEXT"
    top_score = ranked[0][1] if ranked else 0.0
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    low_consensus = (top_score - second_score) < 0.15

    verdict: Verdict = top_verdict  # type: ignore[assignment]
    applied_overrides: list[str] = []

    if verdict == "SCALE" and _has_too_little_data(context):
        verdict = "TEST_NEXT"
        applied_overrides.append("low_data_blocks_scale")

    fatigue_pause = next(
        (
            opinion
            for opinion in final_opinions
            if opinion.agent == "fatigue_detective"
            and opinion.verdict == "PAUSE"
            and opinion.confidence > 0.8
        ),
        None,
    )
    if verdict == "SCALE" and fatigue_pause is not None:
        verdict = _select_without_scale(scores)
        applied_overrides.append("fatigue_pause_blocks_scale")

    risk_block = next(
        (
            opinion
            for opinion in final_opinions
            if opinion.agent == "risk_officer"
            and opinion.verdict in ("PAUSE", "PIVOT")
            and opinion.confidence > 0.7
        ),
        None,
    )
    if verdict == "SCALE" and risk_block is not None:
        verdict = "PIVOT"
        applied_overrides.append("risk_officer_blocks_scale")

    total_score = sum(scores.values())
    if total_score <= 0:
        confidence = 0.0
    elif scores.get(verdict, 0.0) > 0:
        confidence = min(1.0, scores[verdict] / total_score)
    else:
        confidence = min(0.5, top_score / total_score)

    return ConsensusResult(
        verdict=verdict,
        confidence=round(confidence, 4),
        scores={key: round(value, 4) for key, value in scores.items()},
        low_consensus=low_consensus,
        applied_overrides=applied_overrides,
    )


def _first_claim(opinion: Opinion) -> str:
    return opinion.claims[0] if opinion.claims else f"{opinion.agent} voted {opinion.verdict}."


def build_synthesis(consensus: ConsensusResult, final_opinions: list[Opinion]) -> dict[str, Any]:
    aligned = [opinion for opinion in final_opinions if opinion.verdict == consensus.verdict]
    dissent = [opinion for opinion in final_opinions if opinion.verdict != consensus.verdict]
    evidence_bullets = [_first_claim(opinion) for opinion in aligned[:3]]
    if not evidence_bullets and final_opinions:
        evidence_bullets = [_first_claim(opinion) for opinion in final_opinions[:3]]
    if consensus.applied_overrides:
        evidence_bullets.append(
            "Safety override applied: " + ", ".join(consensus.applied_overrides)
        )

    next_action = {
        "SCALE": "Increase budget cautiously while monitoring fatigue and risk signals.",
        "PAUSE": "Stop spend on this creative and inspect the causes in the transcript.",
        "PIVOT": "Keep the learning, change the creative angle, and retest against the same audience.",
        "TEST_NEXT": "Run the next controlled test before scaling spend.",
    }[consensus.verdict]

    return {
        "verdict": consensus.verdict,
        "headline": (
            f"Weighted agent consensus is {consensus.verdict} "
            f"with {consensus.confidence:.0%} consensus confidence."
        ),
        "evidence_bullets": evidence_bullets,
        "dissent": (
            ", ".join(f"{op.agent}: {op.verdict}" for op in dissent)
            if dissent
            else None
        ),
        "next_action": next_action,
        "scores": consensus.scores,
        "low_consensus": consensus.low_consensus,
    }


def _hero_moment(final_opinions: list[Opinion]) -> dict[str, Any] | None:
    changed = next((opinion for opinion in final_opinions if opinion.changed_from), None)
    if changed is None:
        return None
    return {
        "agent": changed.agent,
        "changed_from": changed.changed_from,
        "changed_to": changed.verdict,
        "confidence": changed.confidence,
        "reason": _first_claim(changed),
    }


def _transcript_block(round_: int, type_: str, data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    elif isinstance(data, list):
        data = [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in data]
    return {"round": round_, "type": type_, "data": data}


def _log(debate_id: str, creative_id: str, round_: int, type_: str, agent: str, payload: Any) -> None:
    try:
        evidence_store.log_event(debate_id, creative_id, round_, type_, agent, payload)
    except Exception as exc:
        print(f"[orchestrator] Failed to log event: {exc}")


async def run_debate(
    task: Task,
    agents: list[AgentCard] | None = None,
    config: DebateConfig | None = None,
    *,
    log_events: bool = True,
) -> DebateResult:
    cfg = config or default_config()
    debate_id = task.task_id
    transcript: list[dict[str, Any]] = []
    agent_errors: list[dict[str, Any]] = []

    if agents is None:
        agents = await discover_agents(config=cfg)

    transcript.append(_transcript_block(0, "task", task))
    if log_events:
        _log(debate_id, task.creative_id, 0, "task", "orchestrator", task)
        _log(debate_id, task.creative_id, 0, "agents", "orchestrator", agents)

    if not agents:
        consensus = ConsensusResult(
            verdict="TEST_NEXT",
            confidence=0.0,
            scores={verdict: 0.0 for verdict in VERDICTS},
            low_consensus=True,
            applied_overrides=["no_agents_available"],
        )
        synthesis = build_synthesis(consensus, [])
        result = DebateResult(
            debate_id=debate_id,
            creative_id=task.creative_id,
            campaign_id=task.campaign_id,
            transcript=transcript + [_transcript_block(4, "consensus", consensus)],
            final_opinions=[],
            consensus=consensus,
            synthesis=synthesis,
            hero_moment=None,
            weighted_verdict=consensus.verdict,
            verdict_card=synthesis,
        )
        if log_events:
            _log(debate_id, task.creative_id, 4, "consensus", "orchestrator", consensus)
        return result

    async with httpx.AsyncClient() as client:
        # Round 1: independent opinions. Agents do not see each other yet.
        round1_results = await asyncio.gather(
            *(
                _post_opinion(client, card, task, 1, cfg)
                for card in agents
            ),
            return_exceptions=True,
        )

        opinions_r1: list[Opinion] = []
        for card, result in zip(agents, round1_results):
            if isinstance(result, Exception):
                opinion = _fallback_opinion(card, 1, result)
                agent_errors.append(
                    {"round": 1, "agent": card.name, "error": str(result)}
                )
            else:
                opinion = result
            opinions_r1.append(opinion)
            if log_events:
                _log(debate_id, task.creative_id, 1, "opinion", card.name, opinion)

        transcript.append(_transcript_block(1, "opinions", opinions_r1))

        # Round 2: cross-examination. Every agent sees all Round 1 opinions.
        round2_results = await asyncio.gather(
            *(
                _post_respond(client, card, task, opinions_r1, cfg)
                for card in agents
            ),
            return_exceptions=True,
        )

        messages: list[Message] = []
        for card, result in zip(agents, round2_results):
            if isinstance(result, Exception):
                agent_errors.append(
                    {"round": 2, "agent": card.name, "error": str(result)}
                )
                if log_events:
                    _log(
                        debate_id,
                        task.creative_id,
                        2,
                        "agent_error",
                        card.name,
                        {"error": str(result)},
                    )
                continue
            messages.extend(result)
            if log_events:
                _log(debate_id, task.creative_id, 2, "messages", card.name, result)

        transcript.append(_transcript_block(2, "challenges", messages))

        # Round 3: only challenged agents revise or defend.
        prior_by_agent: dict[str, list[Message]] = defaultdict(list)
        for message in messages:
            if message.type in ("challenge", "evidence_request") and message.to_agent != "ALL":
                prior_by_agent[message.to_agent].append(message)

        card_by_name = {card.name: card for card in agents}
        opinion_by_agent = {opinion.agent: opinion for opinion in opinions_r1}
        challenged_cards = [
            card_by_name[name]
            for name in prior_by_agent
            if name in card_by_name
        ]

        round3_results = await asyncio.gather(
            *(
                _post_opinion(
                    client,
                    card,
                    task,
                    3,
                    cfg,
                    prior_messages=prior_by_agent[card.name],
                    previous_opinion=opinion_by_agent.get(card.name),
                )
                for card in challenged_cards
            ),
            return_exceptions=True,
        )

        revisions: list[Opinion] = []
        for card, result in zip(challenged_cards, round3_results):
            previous = opinion_by_agent.get(card.name)
            if isinstance(result, Exception):
                revision = _fallback_opinion(card, 3, result, previous)
                agent_errors.append(
                    {"round": 3, "agent": card.name, "error": str(result)}
                )
            else:
                revision = result
                if previous and revision.verdict != previous.verdict and revision.changed_from is None:
                    revision = revision.model_copy(update={"changed_from": previous.verdict})
            revisions.append(revision)
            if log_events:
                _log(debate_id, task.creative_id, 3, "revision", card.name, revision)

        transcript.append(_transcript_block(3, "revisions", revisions))

    final_by_agent = {opinion.agent: opinion for opinion in opinions_r1}
    for revision in revisions:
        final_by_agent[revision.agent] = revision
    final_opinions = list(final_by_agent.values())

    if agent_errors:
        transcript.append(_transcript_block(99, "agent_errors", agent_errors))

    consensus = compute_consensus(final_opinions, agents, task.context)
    synthesis = build_synthesis(consensus, final_opinions)
    hero_moment = _hero_moment(final_opinions)

    transcript.append(_transcript_block(4, "consensus", consensus))
    if log_events:
        _log(debate_id, task.creative_id, 4, "consensus", "orchestrator", consensus)
        _log(debate_id, task.creative_id, 4, "synthesis", "orchestrator", synthesis)
        if hero_moment:
            _log(debate_id, task.creative_id, 4, "hero_moment", "orchestrator", hero_moment)

    return DebateResult(
        debate_id=debate_id,
        creative_id=task.creative_id,
        campaign_id=task.campaign_id,
        transcript=transcript,
        final_opinions=final_opinions,
        consensus=consensus,
        synthesis=synthesis,
        hero_moment=hero_moment,
        weighted_verdict=consensus.verdict,
        verdict_card=synthesis,
    )
