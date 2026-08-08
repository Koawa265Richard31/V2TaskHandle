"""注册协作后端闭环集成测试:组长经注册中心动态发现批准组员 → A2A 下发 → 组员执行回传。

串联两个既有测试的断点:
- test_registry_flow.py:注册中心 HTTP 闭环(注册→申请→批准→发现)
- test_agent_to_agent.py:A2A 下发闭环(组长 connect→submit→轮询)

本文件验证中间的串联:组长用注册中心发现的组员 URL 构造 A2AAdapter 并真实下发。
全程 ScriptedChatModel 驱动,零 LLM key。
"""
from __future__ import annotations

import asyncio
import json
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
from langchain_core.messages import HumanMessage

from task_orchestrator.adapters.a2a_executor import LangGraphAgentExecutor
from task_orchestrator.adapters.a2a_server import build_a2a_app, build_agent_card
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.common.config import Settings
from task_orchestrator.common.db import Database
from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry
from task_orchestrator.registry_client import RegistryClient
from task_orchestrator.registry_center.app import build_app

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_member_agent() -> tuple[AgentRegistry, ScriptedChatModel]:
    """组员 PT:member 角色,无 A2AAdapter。本地任务经注入模型的 LocalAdapter 真实完成。"""
    registry = AgentRegistry()
    registry.register(MockCodexAdapter(mock_results={"default": "组员代码任务完成"}), "codex")
    model = ScriptedChatModel(rules=[
        # plan 节点收到"用户目标:..." → 返回本地任务计划
        ("用户目标", ai_text(
            '[{"task_id":"1","description":"设置明天下午3点提醒开会","agent_type":"local","agent_target":"shell","dependencies":[]}]'
        )),
        # monitor 审查本地任务 → PASS
        ("执行结果", ai_text("PASS")),
    ], default_response="已设置提醒:明天下午3点开会")
    registry.register(LocalAdapter(enabled_tools=["shell"], model=model), "local")
    return registry, model


@pytest.fixture
def registry_server(tmp_path):
    """启动真实注册中心 uvicorn。"""
    db = Database(tmp_path / "registry.db")
    app = build_app(db)
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("注册中心启动超时")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    db.close()


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
async def test_dynamic_discovery_and_dispatch(registry_server, member_server):
    """核心验收:组长经注册中心动态发现批准组员 → A2A 下发 → 组员执行回传。"""
    import task_orchestrator.api.server as srv

    # ① 注册中心:组长登记 → 组员登记+申请 → 组长批准
    client = RegistryClient(registry_server)
    leader_id = await client.register("组长PT", "http://127.0.0.1:8000", "leader")
    member_id = await client.register("组员PT", member_server, "member")
    rid = await client.join_request(member_id, "组员PT", member_server, leader_id)
    assert await client.approve(rid, True) == "approved"
    await client.close()

    # ② 组长动态发现:注入 peer_id,调 _refresh_approved 拉取已批准组员
    settings = Settings(_env_file=None, registry_url=registry_server,
                        a2a_role="leader", instance_name="组长PT")
    srv._approved_peers_cache = []
    srv._instance_peer_id = leader_id

    registry = None
    a2a_names: list[str] = []
    try:
        await srv._refresh_approved(settings)
        assert len(srv._approved_peers_cache) == 1
        assert srv._approved_peers_cache[0]["url"] == member_server

        # ③ 组长用动态发现的 URL 构造注册表(计划下发 agent_type=a2a)
        plan_json = json.dumps([{
            "task_id": "1",
            "description": "请在明天下午3点设置提醒开会",
            "agent_type": "a2a",
            "agent_target": member_server,
            "dependencies": [],
        }], ensure_ascii=False)
        model = ScriptedChatModel(rules=[
            ("用户目标", ai_text(plan_json)),      # plan 节点收到"用户目标:..."
            ("执行结果", ai_text("PASS")),         # monitor 审查组员回传结果
        ], default_response="组长已向组员下发任务")

        registry = srv.build_registry(model, role="leader", dynamic_peers=True, settings=settings)
        a2a_names = [n["name"] for n in registry.list_all() if n["type"] == "a2a"]
        assert a2a_names, "组长应动态发现并注册组员 A2A 适配器"

        # ④ 动态适配器默认未连接,需 connect(等价 event_stream 的连接逻辑)
        for name in a2a_names:
            await registry.get(name).connect()

        # ⑤ 跑完整组长图:plan → dispatch(真实 A2A HTTP 下发)→ monitor → review → aggregate
        graph = build_main_agent(model, registry, role="leader")
        result = await graph.ainvoke({
            "messages": [HumanMessage("请让组员设置提醒开会")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })
        task = result["task_plan"][0]
        assert task["status"] == "completed", f"组员执行未完成: {task.get('error')}"
        assert "提醒" in (task.get("result") or "")
        assert len(result["final_response"]) > 0
    finally:
        if registry is not None:
            for name in a2a_names:
                adapter = registry.get(name)
                if adapter is not None:
                    await adapter.close()
        srv._instance_peer_id = None
        srv._approved_peers_cache = []


@pytest.mark.asyncio
async def test_peer_refresh_loop_updates_cache(registry_server):
    """定时轮询确实会刷新已批准组员缓存(短路 interval,轮询式断言)。"""
    import task_orchestrator.api.server as srv

    client = RegistryClient(registry_server)
    leader_id = await client.register("组长PT", "http://127.0.0.1:8000", "leader")
    member_id = await client.register("组员PT", "http://127.0.0.1:8101", "member")
    rid = await client.join_request(member_id, "组员PT", "http://127.0.0.1:8101", leader_id)
    assert await client.approve(rid, True) == "approved"
    await client.close()

    settings = Settings(_env_file=None, registry_url=registry_server,
                        a2a_role="leader", instance_name="组长PT")
    srv._approved_peers_cache = []
    srv._instance_peer_id = leader_id
    loop_task = asyncio.create_task(srv._peer_refresh_loop(0.1, settings))
    try:
        deadline = time.monotonic() + 5
        while not srv._approved_peers_cache:
            await asyncio.sleep(0.1)
            if time.monotonic() > deadline:
                raise AssertionError("定时轮询未刷新已批准组员缓存")
        assert srv._approved_peers_cache[0]["url"] == "http://127.0.0.1:8101"
    finally:
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
        srv._instance_peer_id = None
        srv._approved_peers_cache = []
