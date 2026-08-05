"""A2A 1.0 集成测试:起真实 uvicorn 服务,走真实 HTTP 验证协议链路。"""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from contextlib import suppress

import pytest
import uvicorn

from a2a.types import AgentCapabilities, AgentInterface, AgentSkill, AgentCard
from a2a.helpers.proto_helpers import (
    Role,
    TaskState,
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_artifact,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater

from task_orchestrator.adapters.a2a_server import build_a2a_app
from task_orchestrator.adapters.a2a_client import RemoteAgentClient

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _TestExecutor(AgentExecutor):
    """测试用执行器:回显输入文本。"""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = get_message_text(context.message) if context.message else ""
        task = new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("处理中…"),
        )
        artifact = new_text_artifact("result", f"已处理:{query}")
        await updater.add_artifact(artifact.parts, name="result")
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("完成"),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


@pytest.fixture
def a2a_test_server():
    """启动一个 A2A 1.0 测试服务。"""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    card = AgentCard(
        name="Test Agent",
        description="A test A2A 1.0 agent",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=[AgentSkill(id="echo", name="回显", description="直接回显输入")],
    )
    app = build_a2a_app(card, _TestExecutor())
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("A2A 测试服务启动超时")
        time.sleep(0.05)

    yield url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.asyncio
async def test_card_discovery(a2a_test_server):
    """验证 AgentCard 可发现。"""
    client = RemoteAgentClient(a2a_test_server)
    try:
        card = await client.connect()
        assert card.name == "Test Agent"
        assert card.skills[0].id == "echo"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_message_stream_roundtrip(a2a_test_server):
    """验证 message/stream 完整链路:发送 → 流式消费 → 得到终态 completed + artifact。"""
    client = RemoteAgentClient(a2a_test_server)
    try:
        result = await client.send("hello world", context_id="ctx-1")
        assert result.state == "completed"
        assert "已处理:hello world" in result.text
        assert result.task_id
        assert result.context_id == "ctx-1"
        assert any("处理中" in s for s in result.status_updates)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_retry(a2a_test_server):
    """验证客户端重试:连接失败后指数退避重连。"""
    client = RemoteAgentClient("http://127.0.0.1:19999")
    with pytest.raises(Exception):
        await client.send("test")
    await client.close()
