"""RetrievalAdapter(REST 异步任务)单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import httpx
import pytest
from langchain_core.messages import HumanMessage

from task_orchestrator.adapters.retrieval_adapter import RetrievalAdapter
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry


class _FakeRemote:
    """模拟远端 REST 检索 agent:内存任务队列。"""

    def __init__(self, statuses: dict[str, str] | None = None, content: str = "检索完成"):
        self.tasks: dict[str, str] = {}
        self._statuses = statuses or {}
        self._content = content

    async def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url.path
        if request.method == "GET" and url == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST" and url == "/tasks":
            import json as _json
            body = _json.loads(request.content)
            tid = f"task-{len(self.tasks) + 1}"
            self.tasks[tid] = "working"
            assert "query" in body
            return httpx.Response(200, json={"task_id": tid})
        if request.method == "GET" and url.startswith("/tasks/"):
            tid = url.split("/")[2]
            if url.endswith("/result"):
                return httpx.Response(200, json={"content": self._content})
            status = self._statuses.get(tid, "completed")
            return httpx.Response(200, json={"status": status})
        if request.method == "DELETE" and url.startswith("/tasks/"):
            tid = url.split("/")[2]
            self.tasks.pop(tid, None)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "not found"})


def _make(statuses: dict[str, str] | None = None, content: str = "检索完成") -> tuple[RetrievalAdapter, _FakeRemote]:
    remote = _FakeRemote(statuses=statuses, content=content)
    adapter = RetrievalAdapter(
        base_url="https://retrieval.example.com",
        api_key="secret",
        transport=httpx.MockTransport(remote.handle),
    )
    return adapter, remote


class TestRetrievalAdapter:
    @pytest.mark.asyncio
    async def test_connect_success(self):
        adapter, _ = _make()
        assert await adapter.connect() is True
        assert adapter.is_available

    @pytest.mark.asyncio
    async def test_connect_failure_on_network_error(self):
        async def _boom(request):
            raise httpx.ConnectError("refused")
        adapter = RetrievalAdapter("https://bad.example.com", transport=httpx.MockTransport(_boom))
        assert await adapter.connect() is False
        assert not adapter.is_available

    @pytest.mark.asyncio
    async def test_connect_failure_on_401(self):
        async def _unauth(request):
            return httpx.Response(401, json={"error": "unauthorized"})
        adapter = RetrievalAdapter("https://auth.example.com", transport=httpx.MockTransport(_unauth))
        assert await adapter.connect() is False

    @pytest.mark.asyncio
    async def test_submit_returns_task_id(self):
        adapter, _ = _make()
        await adapter.connect()
        tid = await adapter.submit({"description": "查一下糖尿病指南"})
        assert tid == "task-1"
        assert tid.startswith("task-")

    @pytest.mark.asyncio
    async def test_submit_requires_connect(self):
        adapter, _ = _make()
        with pytest.raises(RuntimeError):
            await adapter.submit({"description": "x"})

    @pytest.mark.asyncio
    async def test_status_mapping(self):
        adapter, remote = _make(statuses={"task-1": "completed"})
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        assert await adapter.status(tid) == "completed"

    @pytest.mark.asyncio
    async def test_status_working(self):
        adapter, _ = _make(statuses={"task-1": "working"})
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        assert await adapter.status(tid) == "running"

    @pytest.mark.asyncio
    async def test_status_failed(self):
        adapter, _ = _make(statuses={"task-1": "failed"})
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        assert await adapter.status(tid) == "failed"

    @pytest.mark.asyncio
    async def test_result(self):
        adapter, _ = _make(content="查到了:糖尿病饮食建议")
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        result = await adapter.result(tid)
        assert "糖尿病" in result

    @pytest.mark.asyncio
    async def test_result_empty(self):
        adapter, _ = _make(content="")
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        assert await adapter.result(tid) is None

    @pytest.mark.asyncio
    async def test_cancel(self):
        adapter, remote = _make()
        await adapter.connect()
        tid = await adapter.submit({"description": "x"})
        assert await adapter.cancel(tid) is True
        assert tid not in remote.tasks

    @pytest.mark.asyncio
    async def test_agent_type(self):
        adapter, _ = _make()
        assert adapter.agent_type == "retrieval"


class TestRetrievalInGraph:
    @pytest.mark.asyncio
    async def test_retrieval_task_through_full_graph(self):
        """注册 retrieval adapter → plan 出检索任务 → dispatch → monitor(轮询) → 审查 → aggregate。"""
        remote = _FakeRemote(statuses={"task-1": "completed"}, content="查到了:糖尿病饮食指南")
        adapter = RetrievalAdapter(
            base_url="https://retrieval.example.com",
            api_key="secret",
            transport=httpx.MockTransport(remote.handle),
        )
        await adapter.connect()

        registry = AgentRegistry()
        registry.register(adapter, "retrieval-web")
        registry.register(MockCodexAdapter(), "codex")

        # plan 生成检索子任务; review 用 PASS
        model = ScriptedChatModel(responses=[
            ai_text("用户想查糖尿病饮食指南"),
            ai_text('[{"task_id":"1","description":"检索糖尿病饮食指南","agent_type":"retrieval","agent_target":"https://retrieval.example.com","dependencies":[]}]'),
            ai_text("规划落地文档"),
            ai_text("开发落地文档"),
            ai_text("PASS"),
            ai_text("已检索到:糖尿病饮食指南"),
        ])
        graph = build_main_agent(model, registry)

        result = await graph.ainvoke({
            "messages": [HumanMessage("查一下糖尿病饮食指南")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })
        plan = result["task_plan"]
        assert len(plan) == 1
        assert plan[0]["status"] == "completed"
        assert "糖尿病" in (plan[0].get("result") or "")

    @pytest.mark.asyncio
    async def test_retrieval_available_by_capability(self):
        """get_by_capability 能按 retrieve 找到已连接的 retrieval adapter。"""
        remote = _FakeRemote()
        adapter = RetrievalAdapter(
            base_url="https://retrieval.example.com",
            transport=httpx.MockTransport(remote.handle),
        )
        await adapter.connect()
        registry = AgentRegistry()
        registry.register(adapter, "retrieval-web")
        found = registry.get_by_capability("retrieve")
        assert found is adapter
