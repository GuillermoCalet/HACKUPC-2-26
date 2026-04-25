"""Small FastAPI scaffold for teammate agent services."""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from orchestrator.a2a import AgentCard, Message, Opinion, OpinionRequest, RespondRequest, Task


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
    return await _maybe_await(result)


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
        return await _call_opinion_fn(
            opinion_fn,
            req.task,
            req.prior_messages,
            req.previous_opinion,
        )

    @app.post("/respond", response_model=list[Message])
    async def respond(req: RespondRequest) -> list[Message]:
        return await _call_respond_fn(respond_fn, req.task, req.opinions)

    return app
