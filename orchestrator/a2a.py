"""Pydantic models for the Creative Boardroom A2A protocol.

The orchestrator and every independent agent service share these models. Keep
them small and explicit so teammate agents can implement the HTTP contract
without depending on any external A2A framework.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Verdict = Literal["SCALE", "PAUSE", "PIVOT", "TEST_NEXT"]
MessageType = Literal["challenge", "evidence_request", "concur", "revision"]
EvidenceType = Literal["metric", "visual", "categorical", "statistical", "system"]


class AgentCard(BaseModel):
    """Public metadata exposed by every agent at /.well-known/agent.json."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    endpoint: str = Field(description="Base URL for this agent service")
    vote_weight: float = Field(default=1.0, ge=0)

    @field_validator("endpoint")
    @classmethod
    def strip_endpoint(cls, value: str) -> str:
        return value.rstrip("/")


class Evidence(BaseModel):
    type: EvidenceType
    key: str
    value: Any
    source: str


class Opinion(BaseModel):
    agent: str
    round: int = Field(ge=1)
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    claims: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    changed_from: Verdict | None = None


class Message(BaseModel):
    id: str
    from_agent: str
    to_agent: str
    type: MessageType
    body: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    in_reply_to: str | None = None


class Task(BaseModel):
    task_id: str
    creative_id: str
    campaign_id: str
    context: dict[str, Any] = Field(default_factory=dict)
    image_path: str | None = None


class OpinionRequest(BaseModel):
    """Payload sent to POST /opinion.

    Round 1 sends only the task. Round 3 also includes prior_messages addressed
    to the agent and the previous opinion when available.
    """

    task: Task
    prior_messages: list[Message] = Field(default_factory=list)
    previous_opinion: Opinion | None = None


class RespondRequest(BaseModel):
    """Payload sent to POST /respond during cross-examination."""

    task: Task
    opinions: list[Opinion] = Field(default_factory=list)


class DebateRequest(BaseModel):
    creative_id: str


class ConsensusResult(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    scores: dict[str, float] = Field(default_factory=dict)
    low_consensus: bool
    applied_overrides: list[str] = Field(default_factory=list)
    scores_before_overrides: dict[str, float] = Field(default_factory=dict)
    scores_after_overrides: dict[str, float] = Field(default_factory=dict)


class DebateResult(BaseModel):
    debate_id: str
    creative_id: str
    campaign_id: str
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    final_opinions: list[Opinion] = Field(default_factory=list)
    consensus: ConsensusResult
    synthesis: dict[str, Any] | None = None
    hero_moment: dict[str, Any] | None = None
    debug: dict[str, Any] | None = None

    # Compatibility for the current Streamlit frontend while it migrates to
    # result["consensus"]["verdict"].
    weighted_verdict: Verdict | None = None
    verdict_card: dict[str, Any] | None = None
