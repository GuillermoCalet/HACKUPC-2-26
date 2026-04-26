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
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET_PATH = Path(os.getenv("PARQUET_PATH", str(BASE_DIR / "pipeline/creative_features.parquet")))
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
    agent_parallelism: int
    agent_call_delay_seconds: float


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
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
        agent_parallelism=max(1, _env_int("AGENT_PARALLELISM", 1)),
        agent_call_delay_seconds=max(0.0, _env_float("AGENT_CALL_DELAY_SECONDS", 0.0)),
    )


async def _gather_limited(
    awaitables: Sequence[Any],
    *,
    limit: int,
    delay_seconds: float = 0.0,
) -> list[Any]:
    if limit <= 1 and delay_seconds > 0:
        results: list[Any] = []
        for index, awaitable in enumerate(awaitables):
            if index:
                await asyncio.sleep(delay_seconds)
            try:
                results.append(await awaitable)
            except Exception as exc:
                results.append(exc)
        return results

    semaphore = asyncio.Semaphore(max(1, limit))

    async def run(awaitable: Any) -> Any:
        async with semaphore:
            return await awaitable

    return await asyncio.gather(
        *(run(awaitable) for awaitable in awaitables),
        return_exceptions=True,
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


def fix_image_path(row: dict[str, Any]) -> dict[str, Any]:
    if "image_path" in row and row["image_path"]:
        base_dir = Path(__file__).resolve().parent.parent
        filename = Path(row["image_path"]).name
        row["image_path"] = str(base_dir / "Smadex_Creative_Intelligence_Dataset_FULL" / "assets" / filename)
    return row


def load_creative_rows(parquet_path: Path | str = DEFAULT_PARQUET_PATH) -> list[dict[str, Any]]:
    path = Path(parquet_path)
    if not path.exists():
        return [fake_creative_context()]

    df = pd.read_parquet(path)
    if "creative_id" not in df.columns:
        raise ValueError(f"{path} must contain a creative_id column")
    return [fix_image_path(json_safe(row)) for row in df.to_dict(orient="records")]


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

    return fix_image_path(json_safe(row.iloc[0].to_dict()))


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


def _text_value(context: dict[str, Any], *names: str, default: str = "unknown") -> str:
    for name in names:
        value = context.get(name)
        if not _is_missing(value) and value != "":
            return str(value)
    return default


def _confirmed_fatigue(context: dict[str, Any]) -> bool:
    status = _text_value(context, "creative_status", default="").lower()
    fatigue_day = _numeric(context, "fatigue_day") or 0.0
    return "fatigue" in status or fatigue_day > 0


def _has_useful_signal(context: dict[str, Any]) -> bool:
    status = _text_value(context, "creative_status", default="").lower()
    ctr_pct = _numeric(context, "ctr_pct") or 0.0
    ipm_pct = _numeric(context, "ipm_pct") or 0.0
    roas = _numeric(context, "overall_roas", "roas") or 0.0
    return (
        "top_performer" in status
        or ctr_pct >= 0.65
        or ipm_pct >= 0.65
        or roas >= 1.15
    )


def _scale_ready_signal(context: dict[str, Any]) -> bool:
    if _has_too_little_data(context) or _confirmed_fatigue(context):
        return False
    status = _text_value(context, "creative_status", default="").lower()
    ctr_pct = _numeric(context, "ctr_pct") or 0.0
    ipm_pct = _numeric(context, "ipm_pct") or 0.0
    cvr_pct = _numeric(context, "cvr_pct") or 0.0
    spend_pct = _numeric(context, "spend_pct", "spend_share_pct") or 1.0
    roas = _numeric(context, "overall_roas", "roas") or 0.0
    top_performer = "top_performer" in status
    strong_metrics = ctr_pct >= 0.75 and ipm_pct >= 0.75 and cvr_pct >= 0.45
    efficient_spend = roas >= 1.20 and spend_pct <= 0.70
    return efficient_spend and (top_performer or strong_metrics)


def _pause_harm_is_clear(context: dict[str, Any], final_opinions: list[Opinion]) -> bool:
    roas = _numeric(context, "overall_roas", "roas")
    spend_pct = _numeric(context, "spend_pct", "spend_share_pct") or 0.0
    ctr_pct = _numeric(context, "ctr_pct") or 0.5
    ipm_pct = _numeric(context, "ipm_pct") or 0.5
    decay_pct = _numeric(context, "ctr_decay_pct") or 0.0
    losing_at_scale = roas is not None and roas < 0.80 and spend_pct >= 0.50
    wasteful_fatigue = (
        (_confirmed_fatigue(context) or decay_pct <= -0.50)
        and spend_pct >= 0.75
        and ctr_pct <= 0.25
        and ipm_pct <= 0.25
        and (roas is None or roas < 1.10)
    )
    hard_visual_or_audience_block = any(
        opinion.verdict == "PAUSE"
        and opinion.agent in {"visual_critic", "audience_simulator"}
        and any(
            token in " ".join(opinion.claims).lower()
            for token in (
                "missing cta",
                "no visible cta",
                "invisible cta",
                "illegible",
                "unreadable",
                "actively creating rejection",
                "distrust",
            )
        )
        for opinion in final_opinions
    )
    return losing_at_scale or wasteful_fatigue or hard_visual_or_audience_block


def _pause_replacement(scores: dict[str, float], context: dict[str, Any]) -> Verdict:
    # PAUSE is a kill switch. If the evidence is uncertainty, TEST_NEXT wins; if
    # the concept has useful signal but the execution is tired, PIVOT wins.
    if _has_too_little_data(context):
        return "TEST_NEXT"
    if _has_useful_signal(context) or scores.get("PIVOT", 0.0) >= scores.get("TEST_NEXT", 0.0):
        return "PIVOT"
    return "TEST_NEXT"


def _select_without_scale(scores: dict[str, float]) -> Verdict:
    candidates = {verdict: score for verdict, score in scores.items() if verdict != "SCALE"}
    if not candidates:
        return "TEST_NEXT"
    if candidates.get("PIVOT", 0.0) == 0 and candidates.get("TEST_NEXT", 0.0) == 0:
        return "TEST_NEXT"
    return max(candidates, key=candidates.get)  # type: ignore[return-value]


def _move_score(scores: dict[str, float], from_verdict: Verdict, to_verdict: Verdict) -> None:
    if from_verdict == to_verdict:
        return
    moved = scores.get(from_verdict, 0.0)
    scores[to_verdict] = scores.get(to_verdict, 0.0) + moved
    scores[from_verdict] = 0.0


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
    scores_before_overrides = dict(scores)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_verdict = ranked[0][0] if ranked else "TEST_NEXT"

    verdict: Verdict = top_verdict  # type: ignore[assignment]
    applied_overrides: list[str] = []
    scores_after_overrides = dict(scores)

    if verdict == "SCALE" and _has_too_little_data(context):
        _move_score(scores_after_overrides, "SCALE", "TEST_NEXT")
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
        previous_verdict = verdict
        verdict = _select_without_scale(scores)
        _move_score(scores_after_overrides, previous_verdict, verdict)
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
    if verdict == "SCALE" and risk_block is not None and not _scale_ready_signal(context):
        _move_score(scores_after_overrides, "SCALE", "PIVOT")
        verdict = "PIVOT"
        applied_overrides.append("risk_officer_blocks_scale")

    if verdict == "PAUSE" and not _pause_harm_is_clear(context, final_opinions):
        previous_verdict = verdict
        verdict = _pause_replacement(scores, context)
        _move_score(scores_after_overrides, previous_verdict, verdict)
        applied_overrides.append(f"pause_requires_clear_harm_to_{verdict.lower()}")

    adjusted_ranked = sorted(scores_after_overrides.items(), key=lambda item: item[1], reverse=True)
    adjusted_top_score = adjusted_ranked[0][1] if adjusted_ranked else 0.0
    adjusted_second_score = adjusted_ranked[1][1] if len(adjusted_ranked) > 1 else 0.0
    low_consensus = (adjusted_top_score - adjusted_second_score) < 0.15

    total_score = sum(scores_after_overrides.values())
    if total_score <= 0:
        confidence = 0.0
    elif scores_after_overrides.get(verdict, 0.0) > 0:
        confidence = min(1.0, scores_after_overrides[verdict] / total_score)
    else:
        confidence = min(0.5, adjusted_top_score / total_score)
    if applied_overrides and scores_before_overrides.get(verdict, 0.0) <= 0:
        confidence = min(confidence, 0.55)

    return ConsensusResult(
        verdict=verdict,
        confidence=round(confidence, 4),
        scores={key: round(value, 4) for key, value in scores_after_overrides.items()},
        low_consensus=low_consensus,
        applied_overrides=applied_overrides,
        scores_before_overrides={key: round(value, 4) for key, value in scores_before_overrides.items()},
        scores_after_overrides={key: round(value, 4) for key, value in scores_after_overrides.items()},
    )


def _first_claim(opinion: Opinion) -> str:
    return opinion.claims[0] if opinion.claims else f"{opinion.agent} voted {opinion.verdict}."


def _fmt_int(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{int(round(value)):,}"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value * 100:.2f}%"


def _fmt_pct_rank(value: float | None) -> str:
    if value is None:
        return "unknown campaign rank"
    return f"better than about {max(0, min(100, int(round(value * 100))))} out of 100 campaign creatives"


def _claim_is_usable(claim: str) -> bool:
    text = claim.strip()
    broken_patterns = (
        " of %",
        " of -",
        "$for every $",
        "indicates this creative is returning $",
        "ctr_",
        "ipm_",
        "cvr_",
        "ci_",
    )
    return bool(text) and not any(pattern in text.lower() for pattern in broken_patterns)


def _first_usable_claim(final_opinions: list[Opinion], *agent_names: str) -> str | None:
    for opinion in final_opinions:
        if opinion.agent not in agent_names:
            continue
        has_grounded_evidence = any(evidence.type in {"visual", "categorical"} for evidence in opinion.evidence)
        if not has_grounded_evidence:
            continue
        for claim in opinion.claims:
            if _claim_is_usable(claim):
                return claim
    return None


def _performance_bullet(context: dict[str, Any]) -> str:
    installs = _numeric(context, "installs", "conversions", "total_conversions")
    impressions = _numeric(context, "impressions", "total_impressions")
    roas = _numeric(context, "overall_roas", "roas")
    ipm_pct = _numeric(context, "ipm_pct")
    if roas is not None and installs is not None:
        return (
            f"This creative has produced {_fmt_int(installs)} installs and returns about "
            f"${roas:.2f} for every $1 spent; that means the concept has real value, "
            f"even if the current execution may not be safe to push unchanged."
        )
    if installs is not None and impressions is not None:
        return (
            f"This creative has {_fmt_int(installs)} installs from {_fmt_int(impressions)} impressions, "
            f"so the agents are judging a real delivery history rather than a tiny sample."
        )
    if ipm_pct is not None:
        return (
            f"Install pull is {_fmt_pct_rank(ipm_pct)}, which anchors the recommendation in campaign-relative performance."
        )
    return "The available performance context is limited, so the verdict relies more heavily on agent agreement and creative evidence."


def _fatigue_bullet(context: dict[str, Any]) -> str:
    first_ctr = _numeric(context, "first_7d_ctr")
    last_ctr = _numeric(context, "last_7d_ctr")
    decay = _numeric(context, "ctr_decay_pct")
    active_days = _numeric(context, "active_days", "creative_age_days")
    status = _text_value(context, "creative_status", default="unknown")
    if first_ctr is not None and last_ctr is not None and decay is not None:
        return (
            f"Click interest fell from {_fmt_rate(first_ctr)} in the launch week to "
            f"{_fmt_rate(last_ctr)} recently, a {abs(decay) * 100:.0f}% drop; "
            f"that points to audience wear-out rather than a brand-new performance read."
        )
    if active_days is not None:
        return (
            f"The creative has been active for {_fmt_int(active_days)} days and is labelled {status}; "
            f"that history matters when deciding whether to scale the exact asset or refresh it."
        )
    return f"The creative status is {status}, so the fatigue read is part of the final recommendation."


def _creative_context_bullet(context: dict[str, Any], final_opinions: list[Opinion]) -> str:
    claim = _first_usable_claim(final_opinions, "visual_critic", "audience_simulator")
    if claim:
        return claim
    format_ = _text_value(context, "format")
    theme = _text_value(context, "theme", "primary_theme")
    cta = _text_value(context, "cta_text", default="")
    if cta:
        return (
            f"The asset is a {format_} creative around the {theme} hook with a '{cta}' call-to-action; "
            f"the next variant should change one visible execution element so the test is easy to read."
        )
    return (
        f"The asset is a {format_} creative around the {theme} hook; keep that context in the next test "
        f"so the result compares the execution, not an entirely different idea."
    )


def _headline(verdict: Verdict, context: dict[str, Any]) -> str:
    status = _text_value(context, "creative_status", default="creative")
    if verdict == "SCALE":
        return "Scale this creative carefully because it is still bringing in users efficiently and no hard safety block won the debate."
    if verdict == "PAUSE":
        return "Pause this exact creative because the debate found clear evidence that continued spend is likely to waste budget."
    if verdict == "PIVOT":
        return f"Pivot this {status} creative because it has useful signal, but the current execution is showing wear-out or execution risk."
    return "Run one cleaner next test because the agents did not have a strong enough signal to scale or kill this creative."


def _change_target(context: dict[str, Any], final_opinions: list[Opinion]) -> str:
    visual_claim = (_first_usable_claim(final_opinions, "visual_critic", "audience_simulator") or "").lower()
    if "cta" in visual_claim or "call-to-action" in visual_claim or _text_value(context, "cta_text", default=""):
        return "CTA treatment"
    if _numeric(context, "ctr_decay_pct") is not None or _confirmed_fatigue(context):
        return "first frame and opening hook"
    if _text_value(context, "hook_type", default="unknown") != "unknown":
        return "hook framing"
    return "main visual hierarchy"


def _action_plan(verdict: Verdict, context: dict[str, Any], final_opinions: list[Opinion]) -> dict[str, Any]:
    theme = _text_value(context, "theme", "primary_theme", default="core")
    cta = _text_value(context, "cta_text", default="the current CTA")
    target = _change_target(context, final_opinions)

    if verdict == "SCALE":
        next_action = (
            f"Increase budget in controlled steps while keeping the {theme} hook, and check recent click interest before each increase."
        )
        keep = f"Keep the {theme} hook and current audience."
        change = "Do not change the concept before the scale test; only prepare a fresh backup variant."
        test = "Raise spend gradually and compare recent click interest against the current baseline."
    elif verdict == "PAUSE":
        next_action = (
            f"Stop this exact asset for now and move spend to healthier creatives while a replacement with a new {target} is built."
        )
        keep = f"Keep any proven learning from the {theme} concept."
        change = f"Replace the current {target} before spending more on this execution."
        test = "Relaunch only when the replacement has a clear hypothesis and budget cap."
    elif verdict == "PIVOT":
        next_action = (
            f"Keep the {theme} idea, but make a new version that changes the {target}; if the CTA stays, make '{cta}' easier to notice and tap."
        )
        keep = f"Keep the {theme} concept and the audience that already generated signal."
        change = f"Change the {target}, because the current execution is wearing out or limiting conversion."
        test = "Run the refreshed version against the current asset with one clear changed element."
    else:
        next_action = (
            f"Run a small challenger test that changes only the {target}, then decide after the cleaner comparison."
        )
        keep = f"Keep the {theme} premise so the next test isolates execution quality."
        change = f"Change only the {target}; avoid changing offer, audience, and format at once."
        test = "Use a capped budget and compare the challenger against this creative before scaling or pausing."

    return {
        "next_action": next_action,
        "keep": keep,
        "change": change,
        "test": test,
        "creative_changes": [
            {"title": "Keep", "explanation": keep},
            {"title": "Change", "explanation": change},
            {"title": "Test", "explanation": test},
        ],
    }


def build_synthesis(
    consensus: ConsensusResult,
    final_opinions: list[Opinion],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    aligned = [opinion for opinion in final_opinions if opinion.verdict == consensus.verdict]
    dissent = [opinion for opinion in final_opinions if opinion.verdict != consensus.verdict]

    evidence_bullets = [
        _performance_bullet(context),
        _fatigue_bullet(context),
        _creative_context_bullet(context, final_opinions),
    ]
    for opinion in aligned:
        for claim in opinion.claims:
            if len(evidence_bullets) >= 3:
                break
            if _claim_is_usable(claim):
                evidence_bullets.append(claim)
    if consensus.applied_overrides:
        evidence_bullets.append(
            "Consensus guardrail applied: " + ", ".join(consensus.applied_overrides)
        )

    action_plan = _action_plan(consensus.verdict, context, final_opinions)

    return {
        "verdict": consensus.verdict,
        "headline": _headline(consensus.verdict, context),
        "evidence_bullets": evidence_bullets,
        "dissent": (
            ", ".join(f"{op.agent}: {op.verdict}" for op in dissent[:3])
            if dissent
            else None
        ),
        **action_plan,
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


def _vote_debug(opinions: list[Opinion]) -> list[dict[str, Any]]:
    return [
        {
            "agent": opinion.agent,
            "verdict": opinion.verdict,
            "confidence": opinion.confidence,
            "changed_from": opinion.changed_from,
            "first_claim": _first_claim(opinion),
        }
        for opinion in opinions
    ]


def build_decision_debug(
    round1_opinions: list[Opinion],
    revisions: list[Opinion],
    final_opinions: list[Opinion],
    consensus: ConsensusResult,
) -> dict[str, Any]:
    return {
        "round1_votes": _vote_debug(round1_opinions),
        "round3_votes": _vote_debug(revisions),
        "final_votes": _vote_debug(final_opinions),
        "scores_before_overrides": consensus.scores_before_overrides or consensus.scores,
        "scores_after_overrides": consensus.scores_after_overrides or consensus.scores,
        "applied_overrides": consensus.applied_overrides,
        "final_verdict": consensus.verdict,
        "final_confidence": consensus.confidence,
    }


def _print_decision_debug(debate_id: str, debug: dict[str, Any]) -> None:
    print(f"[orchestrator][debug] debate={debate_id} round1={debug['round1_votes']}")
    print(f"[orchestrator][debug] debate={debate_id} round3={debug['round3_votes']}")
    print(
        f"[orchestrator][debug] debate={debate_id} scores_before={debug['scores_before_overrides']} "
        f"scores_after={debug['scores_after_overrides']} overrides={debug['applied_overrides']} "
        f"final={debug['final_verdict']}"
    )


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
            scores_before_overrides={verdict: 0.0 for verdict in VERDICTS},
            scores_after_overrides={verdict: 0.0 for verdict in VERDICTS},
        )
        synthesis = build_synthesis(consensus, [], task.context)
        debug = build_decision_debug([], [], [], consensus)
        result = DebateResult(
            debate_id=debate_id,
            creative_id=task.creative_id,
            campaign_id=task.campaign_id,
            transcript=transcript + [_transcript_block(4, "consensus", consensus)],
            final_opinions=[],
            consensus=consensus,
            synthesis=synthesis,
            hero_moment=None,
            debug=debug,
            weighted_verdict=consensus.verdict,
            verdict_card=synthesis,
        )
        if log_events:
            _log(debate_id, task.creative_id, 4, "consensus", "orchestrator", consensus)
        return result

    async with httpx.AsyncClient() as client:
        # Round 1: independent opinions. Agents do not see each other yet.
        if log_events:
            for card in agents:
                _log(
                    debate_id,
                    task.creative_id,
                    1,
                    "agent_call",
                    "orchestrator",
                    {
                        "from_agent": "orchestrator",
                        "to_agent": card.name,
                        "purpose": "request_independent_opinion",
                    },
                )
        round1_results = await _gather_limited(
            [
                _post_opinion(client, card, task, 1, cfg)
                for card in agents
            ],
            limit=cfg.agent_parallelism,
            delay_seconds=cfg.agent_call_delay_seconds,
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
        if log_events:
            for card in agents:
                _log(
                    debate_id,
                    task.creative_id,
                    2,
                    "agent_call",
                    "orchestrator",
                    {
                        "from_agent": "orchestrator",
                        "to_agent": card.name,
                        "purpose": "request_cross_examination",
                    },
                )
        round2_results = await _gather_limited(
            [
                _post_respond(client, card, task, opinions_r1, cfg)
                for card in agents
            ],
            limit=cfg.agent_parallelism,
            delay_seconds=cfg.agent_call_delay_seconds,
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

        if log_events:
            for card in challenged_cards:
                _log(
                    debate_id,
                    task.creative_id,
                    3,
                    "agent_call",
                    "orchestrator",
                    {
                        "from_agent": "orchestrator",
                        "to_agent": card.name,
                        "purpose": "request_revision_after_challenge",
                    },
                )
        round3_results = await _gather_limited(
            [
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
            ],
            limit=cfg.agent_parallelism,
            delay_seconds=cfg.agent_call_delay_seconds,
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
    synthesis = build_synthesis(consensus, final_opinions, task.context)
    hero_moment = _hero_moment(final_opinions)
    debug = build_decision_debug(opinions_r1, revisions, final_opinions, consensus)
    _print_decision_debug(debate_id, debug)

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
        debug=debug,
        weighted_verdict=consensus.verdict,
        verdict_card=synthesis,
    )
