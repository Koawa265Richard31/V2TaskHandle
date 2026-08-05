"""Adapter 层测试。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from task_orchestrator.adapters.base import BaseAdapter
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.adapters.retrieval_adapter import RetrievalAdapter
from task_orchestrator.registry import AgentRegistry


class TestMockCodex:
    @pytest.mark.asyncio
    async def test_submit_and_result(self):
        adapter = MockCodexAdapter()
        tid = await adapter.submit({"description": "分析代码"})
        assert tid.startswith("mock_codex_")
        result = await adapter.result(tid)
        assert "Mock Codex" in result

    @pytest.mark.asyncio
    async def test_is_available(self):
        assert MockCodexAdapter().is_available


class TestLocalAdapter:
    def test_enabled_tools(self):
        adapter = LocalAdapter(enabled_tools=["shell", "file"])
        assert adapter.is_available
        assert "shell" in adapter.enabled_tools
        assert "email" not in adapter.enabled_tools

    def test_empty_tools(self):
        adapter = LocalAdapter(enabled_tools=[])
        assert not adapter.is_available


class TestAgentRegistry:
    def test_register_and_get(self):
        registry = AgentRegistry()
        mock = MockCodexAdapter()
        registry.register(mock, "test_codex")
        assert registry.get("test_codex") is mock

    def test_get_by_type(self):
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(), "codex_1")
        registry.register(LocalAdapter(), "local_1")
        assert registry.get_by_type("codex") is not None
        assert registry.get_by_type("a2a") is None

    def test_list_all(self):
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(), "c1")
        all_agents = registry.list_all()
        assert len(all_agents) == 1
        assert all_agents[0]["type"] == "codex"

    def test_summary(self):
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(), "c1")
        summary = registry.agents_summary()
        assert "codex" in summary
        assert "可用" in summary


class TestCapabilities:
    def test_mock_codex_capability(self):
        assert "code" in MockCodexAdapter().capabilities

    def test_local_capabilities(self):
        local = LocalAdapter(enabled_tools=["shell", "file"])
        assert "code" in local.capabilities
        assert "doc" in local.capabilities

    def test_retrieval_capability(self):
        assert "retrieve" in RetrievalAdapter("http://x").capabilities

    def test_get_by_capability(self):
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(), "codex")
        registry.register(LocalAdapter(enabled_tools=["shell", "file"]), "local")
        assert registry.get_by_capability("code") is not None
        assert registry.get_by_capability("doc") is not None
        assert registry.get_by_capability("retrieve") is None

    def test_get_by_capability_respects_availability(self):
        registry = AgentRegistry()
        local = LocalAdapter(enabled_tools=[])
        registry.register(local, "empty_local")
        assert registry.get_by_capability("doc") is None

    def test_summary_includes_capabilities(self):
        registry = AgentRegistry()
        registry.register(MockCodexAdapter(), "codex")
        summary = registry.agents_summary()
        assert "code" in summary
