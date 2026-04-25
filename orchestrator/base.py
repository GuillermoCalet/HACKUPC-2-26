from fastapi import FastAPI
from orchestrator.a2a import AgentCard, OpinionRequest, RespondRequest, Opinion, Message


def make_agent(
    card: AgentCard,
    opinion_fn,   # async (task: Task, prior_messages: list[Message]) -> Opinion
    respond_fn,   # async (task: Task, opinions: list[Opinion]) -> list[Message]
) -> FastAPI:
    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent.json")
    def get_card():
        return card.model_dump()

    @app.post("/opinion")
    async def opinion(req: OpinionRequest) -> Opinion:
        return await opinion_fn(req.task, req.prior_messages)

    @app.post("/respond")
    async def respond(req: RespondRequest) -> list[Message]:
        return await respond_fn(req.task, req.opinions)

    return app
