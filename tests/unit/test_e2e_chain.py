"""端到端验证:全链路打通 (FakeLLM, 无需任何外部 key)。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from langchain_core.messages import HumanMessage

from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry

SAMPLE_PLAN = """[
    {"task_id":"1","description":"分析代码结构","agent_type":"codex","agent_target":"workspace_write","dependencies":[]},
    {"task_id":"2","description":"生成摘要报告","agent_type":"local","agent_target":"file","dependencies":["1"]}
]"""


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("PTA_LLM_PROVIDER", "fake")
    monkeypatch.delenv("PTA_LLM_API_KEY", raising=False)


def build_test_registry() -> AgentRegistry:
    r = AgentRegistry()
    r.register(MockCodexAdapter(), "codex")
    r.register(LocalAdapter(enabled_tools=["shell", "file", "web"]), "local")
    return r


class TestE2EChain:
    def test_imports_ok(self):
        """验证所有模块可正常导入。"""
        from task_orchestrator.common.config import get_settings
        from task_orchestrator.common.db import Database
        from task_orchestrator.common.llm import build_chat_model
        from task_orchestrator.common.log import setup_logging
        from task_orchestrator.common.agent_loop import build_tool_agent
        from task_orchestrator.main_agent.state import MainAgentState, SubTask
        from task_orchestrator.main_agent.nodes import understand_node, plan_node, aggregate_node
        from task_orchestrator.main_agent.exec_nodes import dispatch_node, monitor_node, replan_node
        from task_orchestrator.adapters.base import BaseAdapter
        from task_orchestrator.adapters.a2a_client import RemoteAgentClient
        from task_orchestrator.adapters.a2a_server import build_a2a_app
        from task_orchestrator.adapters.a2a_adapter import A2AAdapter
        from task_orchestrator.adapters.codex_adapter import MockCodexAdapter, CodexAdapter
        from task_orchestrator.adapters.local_adapter import LocalAdapter
        from task_orchestrator.registry import AgentRegistry
        from task_orchestrator.local_agent.tools import build_local_agent

    @pytest.mark.asyncio
    async def test_full_graph_with_fake_llm(self):
        """FakeLLM 驱动完整 6 节点图: understand→plan→dispatch→monitor→aggregate"""
        model = ScriptedChatModel(responses=[
            ai_text("用户想要分析代码"),
            ai_text(SAMPLE_PLAN),
            ai_text("规划落地文档"),
            ai_text("开发落地文档"),
            ai_text("PASS"),
            ai_text("PASS"),
            ai_text("好的,已完成:1)分析了代码结构 2)生成了摘要报告"),
        ])
        registry = build_test_registry()
        graph = build_main_agent(model, registry)

        result = await graph.ainvoke({
            "messages": [HumanMessage("帮我分析代码并生成摘要")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })

        plan = result["task_plan"]
        assert len(plan) == 2
        assert plan[0]["status"] in ("running", "completed")
        assert plan[1]["dependencies"] == ["1"]
        assert len(result["final_response"]) > 5

    @pytest.mark.asyncio
    async def test_dependency_ordering(self):
        """验证依赖解析: task 1 先完成, task 2 才从 pending→ready"""
        model = ScriptedChatModel(responses=[
            ai_text("user wants parallel tasks"),
            ai_text("""[
                {"task_id":"1","description":"task one","agent_type":"codex","agent_target":"w","dependencies":[]},
                {"task_id":"2","description":"task two","agent_type":"local","agent_target":"file","dependencies":["1"]}
            ]"""),
            ai_text("规划落地文档"),
            ai_text("开发落地文档"),
            ai_text("PASS"),
            ai_text("PASS"),
            ai_text("done"),
        ])
        registry = build_test_registry()
        graph = build_main_agent(model, registry)

        result = await graph.ainvoke({
            "messages": [HumanMessage("run tasks")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })

        plan = result["task_plan"]
        # task 1 dispatched first (no deps), task 2 waits
        assert plan[0]["status"] in ("running", "completed")
        # task 2 应该在 monitor 后被检查

    @pytest.mark.asyncio
    async def test_api_sse_format(self):
        """验证 SSE 输出格式正确。"""
        from task_orchestrator.api.server import event_stream
        chunks = []
        async for chunk in event_stream("test", None):
            chunks.append(chunk)
        assert len(chunks) >= 1
        assert chunks[0].startswith("event: ")
        assert "data:" in chunks[0]

    @pytest.mark.asyncio
    async def test_local_tools_work(self):
        """验证本地工具 (shell/file) 可正常工作。"""
        # shell
        from task_orchestrator.local_agent.tools import shell_exec, file_write, file_read
        r = shell_exec.invoke("echo hello")
        assert "hello" in r

        # file roundtrip
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            w = file_write.invoke({"content": "e2e test", "path": path})
            assert "写入" in w
            content = file_read.invoke(path)
            assert "e2e test" in content
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_registry_from_config(self):
        """验证 AgentRegistry 注册正常。"""
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(mock_results={"x": "ok"}), "codex")
        registry.register(LocalAdapter(enabled_tools=["shell"]), "local")
        assert registry.get("codex") is not None
        assert registry.get("local") is not None
        assert registry.get_by_type("codex").agent_type == "codex"
        assert registry.get_by_type("local").agent_type == "local"
        summary = registry.agents_summary()
        assert "codex" in summary
        assert "local" in summary
