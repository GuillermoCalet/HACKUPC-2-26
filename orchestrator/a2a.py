from pydantic import BaseModel
from typing import Literal, Optional
from datetime import datetime


class AgentCard(BaseModel):
    name: str
    description: str
    skills: list[str]
    endpoint: str
    vote_weight: float


class Evidence(BaseModel):
    type: Literal["metric", "visual", "categorical"]
    key: str
    value: str | float
    source: str


class Opinion(BaseModel):
    agent: str
    round: int
    verdict: Literal["SCALE", "PAUSE", "PIVOT", "TEST_NEXT"]
    confidence: float
    claims: list[str]
    evidence: list[Evidence]
    changed_from: Optional[str] = None


class Message(BaseModel):
    id: str
    from_agent: str
    to_agent: str
    type: Literal["challenge", "evidence_request", "concur", "revision"]
    in_reply_to: Optional[str] = None
    body: str
    timestamp: datetime


class Task(BaseModel):
    task_id: str
    creative_id: str
    campaign_id: str
    context: dict
    image_path: str


class OpinionRequest(BaseModel):
    task: Task
    prior_messages: list[Message] = []


class RespondRequest(BaseModel):
    task: Task
    opinions: list[Opinion]
