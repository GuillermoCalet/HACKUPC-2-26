"""Small FastAPI scaffold for teammate agent services."""
from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from orchestrator.a2a import AgentCard, Evidence, Message, Opinion, OpinionRequest, RespondRequest, Task


logger = logging.getLogger(__name__)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_opinion_fn(
    opinion_fn: Callable[..., Any],
    task: Task,
    prior_messages: list[Message],
    previous_opinion: Opinion | None,
) -> Opinion:
    """Call old or new opinion functions without forcing teammate rewrites."""

    signature = inspect.signature(opinion_fn)
    accepts_varargs = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if accepts_varargs or len(signature.parameters) >= 3:
        result = opinion_fn(task, prior_messages, previous_opinion)
    else:
        result = opinion_fn(task, prior_messages)
    return await _maybe_await(result)


async def _call_respond_fn(
    respond_fn: Callable[..., Any],
    task: Task,
    opinions: list[Opinion],
) -> list[Message]:
    result = respond_fn(task, opinions)
    messages = await _maybe_await(result)
    if messages is None:
        return []
    if not isinstance(messages, list):
        logger.warning("respond_fn returned %s instead of list[Message]", type(messages).__name__)
        return []
    return messages


def make_agent(
    card: AgentCard,
    opinion_fn: Callable[..., Any],
    respond_fn: Callable[..., Any],
) -> FastAPI:
    """Create an A2A-compatible FastAPI app for an independent agent.

    Teammate integration point:
    - opinion_fn(task, prior_messages) -> Opinion
    - optionally opinion_fn(task, prior_messages, previous_opinion) -> Opinion
    - respond_fn(task, opinions) -> list[Message]
    """

    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent.json", response_model=AgentCard)
    def get_card() -> AgentCard:
        return card

    @app.post("/opinion", response_model=Opinion)
    async def opinion(req: OpinionRequest) -> Opinion:
        try:
            return await _call_opinion_fn(
                opinion_fn,
                req.task,
                req.prior_messages,
                req.previous_opinion,
            )
        except Exception as exc:
            logger.exception("[%s] /opinion failed; returning safe fallback", card.name)
            round_num = 3 if req.prior_messages else 1
            changed_from = None
            if req.previous_opinion and req.previous_opinion.verdict != "TEST_NEXT":
                changed_from = req.previous_opinion.verdict
            return Opinion(
                agent=card.name,
                round=round_num,
                verdict="TEST_NEXT",
                confidence=0.25,
                claims=[
                    "Agent failed while forming an opinion; defaulting to TEST_NEXT for safety.",
                ],
                evidence=[
                    Evidence(
                        type="system",
                        key="agent_runtime_error",
                        value=str(exc),
                        source=card.name,
                    )
                ],
                changed_from=changed_from,
            )

    @app.post("/respond", response_model=list[Message])
    async def respond(req: RespondRequest) -> list[Message]:
        try:
            return await _call_respond_fn(respond_fn, req.task, req.opinions)
        except Exception:
            logger.exception("[%s] /respond failed; returning no messages", card.name)
            return []

    return app
