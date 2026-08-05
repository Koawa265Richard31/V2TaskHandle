"""A2A 1.0 服务端装配:AgentCard + AgentExecutor → Starlette 应用。"""
from __future__ import annotations

import logging

import uvicorn
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("a2a.server")


def build_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    skills: list[AgentSkill],
    streaming: bool = True,
    version: str = "1.0.0",
) -> AgentCard:
    """构造 A2A 1.0 AgentCard。"""
    return AgentCard(
        name=name,
        description=description,
        version=version,
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=streaming),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=skills,
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """鉴权中间件:AgentCard 路径豁免,其他需 X-API-Key。"""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/.well-known/"):
            return await call_next(request)
        if request.headers.get("X-API-Key") != self.api_key:
            return JSONResponse({"error": "invalid or missing X-API-Key"}, status_code=401)
        return await call_next(request)


def build_a2a_app(card: AgentCard, executor: AgentExecutor, api_key: str = "") -> Starlette:
    """装配 A2A 1.0 Starlette 应用。"""
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = []
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, "/"))
    app = Starlette(routes=routes)
    if api_key:
        app.add_middleware(ApiKeyMiddleware, api_key=api_key)
    return app


def run_agent(app: Starlette, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")
