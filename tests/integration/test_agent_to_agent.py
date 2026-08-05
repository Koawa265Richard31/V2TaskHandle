"""A2A 下发集成测试:组长 PT 通过 A2A 对组员 PT 下发子任务,组员执行后回传结果。

起真实 uvicorn 组员 A2A 服务端(LangGraphAgentExecutor 包脚本化 Main Agent 图),
组长侧用 A2AAdapter connect → submit → 轮询 status/result,断言端到端下发链路。
"""
from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
import uvicorn

from task_orchestrator.adapters.a2a_adapter import A2AAdapter
from task_orchestrator.adapters.a2a_executor import LangGraphAgentExecutor
from task_orchestrator.adapters.a2a_server import build_a2a_app, build_agent_card
from task_orchestrator.adapters.base import BaseAdapter
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_member_agent() -> tuple[AgentRegistry, ScriptedChatModel]:
    """组员 PT:member 角色,无 A2AAdapter(结构上禁下发)。"""
    registry = AgentRegistry()
    registry.register(MockCodexAdapter(mock_results={"default": "组员代码任务完成"}), "codex")
    # 用关键词规则匹配各节点输入,避免依赖 FIFO 调用顺序:
    # understand 收到原始消息("下发")→ 意图总结;plan 收到"用户目标"→ 计划 JSON;
    # aggregate 收到计划文本 → 完成语
    model = ScriptedChatModel(rules=[
        ("用户目标", ai_text(
            '[{"task_id":"1","description":"设置明天下午3点提醒开会","agent_type":"local","agent_target":"shell","dependencies":[]}]'
        )),
        ("下发", ai_text("用户想要设置提醒")),
        ("好的,我将按以下计划执行", ai_text("已设置提醒:明天下午3点开会")),
    ], default_response="已设置提醒:明天下午3点开会")
    return registry, model


@pytest.fixture
def member_server():
    """启动组员 PT 的 A2A 服务端。"""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    registry, model = build_member_agent()
    graph = build_main_agent(model, registry, role="member")

    card = build_agent_card(
        name="Team Member PT",
        description="接收组长下发的子任务并在本地规划执行",
        url=url,
        skills=[],
        streaming=True,
    )
    app = build_a2a_app(card, LangGraphAgentExecutor(graph, "Team Member PT"))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("组员 A2A 服务启动超时")
        time.sleep(0.05)

    yield url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.asyncio
async def test_leader_dispatches_to_member(member_server):
    """核心验收:组长 PT 对组员 PT 下发子任务并拿到执行结果。"""
    adapter = A2AAdapter(member_server)
    await adapter.connect()
    assert adapter.is_available

    external_id = await adapter.submit({
        "description": "请在明天下午3点设置提醒开会",
        "agent_type": "a2a",
        "agent_target": member_server,
    })
    assert external_id.startswith("a2a_")

    # 轮询直到终态
    for _ in range(50):
        status = await adapter.status(external_id)
        if status in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)

    assert status == "completed", f"组员执行失败: status={status}"
    result = await adapter.result(external_id)
    assert result, "下发结果不应为空"
    assert "提醒" in result

    await adapter.close()


@pytest.mark.asyncio
async def test_member_registry_has_no_a2a():
    """权限验收:组员注册表结构上不含 A2AAdapter,无法向其他 agent 下发。"""
    registry, _ = build_member_agent()
    types = [a["type"] for a in registry.list_all()]
    assert "a2a" not in types
    assert all(not isinstance(a, A2AAdapter) for a in registry._adapters.values())


def test_leader_can_register_a2a():
    """组长注册表含 A2AAdapter(可下发)。"""
    registry = AgentRegistry()
    registry.register(MockCodexAdapter(), "codex")
    registry.register(LocalAdapterStub(), "a2a")
    types = [a["type"] for a in registry.list_all()]
    assert "a2a" in types


class LocalAdapterStub(BaseAdapter):
    @property
    def agent_type(self) -> str:
        return "a2a"

    @property
    def is_available(self) -> bool:
        return True

    async def submit(self, task: dict) -> str:
        return "stub"

    async def status(self, external_id: str) -> str:
        return "completed"

    async def result(self, external_id: str) -> str | None:
        return "stub result"

    async def cancel(self, external_id: str) -> bool:
        return False
