"""Main Agent 节点与图测试 (FakeLLM 注入)。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from langchain_core.messages import HumanMessage

from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.main_agent.nodes import (
    understand_node,
    plan_node,
    aggregate_node,
)


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("PTA_LLM_PROVIDER", "fake")
    monkeypatch.delenv("PTA_LLM_API_KEY", raising=False)


SAMPLE_PLAN_JSON = """[
    {"task_id":"1","description":"分析本周代码提交","agent_type":"codex","agent_target":"workspace_write","dependencies":[]},
    {"task_id":"2","description":"查询未完成任务","agent_type":"a2a","agent_target":"http://localhost:10001","dependencies":[]},
    {"task_id":"3","description":"生成周报并发送邮件","agent_type":"local","agent_target":"email","dependencies":["1","2"]}
]"""


class TestUnderstandNode:
    @pytest.mark.asyncio
    async def test_summarizes_user_request(self):
        model = ScriptedChatModel(
            rules=[("整理", ai_text("用户想要整理本周工作并生成报告"))]
        )
        state = {"messages": [HumanMessage("帮我整理本周工作")], "user_request": "", "task_plan": [], "final_response": ""}
        result = await understand_node(state, model=model)
        assert "整理" in result["user_request"]


class TestPlanNode:
    @pytest.mark.asyncio
    async def test_parses_valid_json_plan(self):
        model = ScriptedChatModel(
            rules=[("整理", ai_text(SAMPLE_PLAN_JSON))]
        )
        state = {
            "messages": [],
            "user_request": "用户想要整理本周工作",
            "task_plan": [],
            "final_response": "",
        }
        result = await plan_node(state, model=model)
        plan = result["task_plan"]
        assert len(plan) == 3
        assert plan[0]["task_id"] == "1"
        assert plan[0]["agent_type"] == "codex"
        assert plan[1]["agent_type"] == "a2a"
        assert plan[2]["agent_type"] == "local"
        assert plan[2]["dependencies"] == ["1", "2"]

    @pytest.mark.asyncio
    async def test_handles_markdown_wrapped_json(self):
        wrapped = '```json\n[{"task_id":"1","description":"分析代码","agent_type":"codex","agent_target":"workspace_write","dependencies":[]}]\n```'
        model = ScriptedChatModel(rules=[("目标", ai_text(wrapped))])
        state = {"messages": [], "user_request": "test", "task_plan": [], "final_response": ""}
        result = await plan_node(state, model=model)
        assert len(result["task_plan"]) == 1

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        model = ScriptedChatModel(rules=[("x", ai_text("not valid json {["))])
        state = {"messages": [], "user_request": "test", "task_plan": [], "final_response": ""}
        result = await plan_node(state, model=model)
        assert result["task_plan"] == []

    @pytest.mark.asyncio
    async def test_injects_agents_info(self):
        model = ScriptedChatModel(responses=[
            ai_text(SAMPLE_PLAN_JSON),
        ])
        state = {"messages": [], "user_request": "test", "task_plan": [], "final_response": ""}
        result = await plan_node(state, model=model, agents_info="Available: codex(本地代码)")
        assert len(result["task_plan"]) == 3


class TestAggregateNode:
    @pytest.mark.asyncio
    async def test_generates_human_readable(self):
        model = ScriptedChatModel(responses=[
            ai_text("好的,我会按计划执行:先分析代码,再查询任务,最后生成周报"),
        ])
        plan = [
            {"task_id": "1", "description": "分析代码", "agent_type": "codex", "agent_target": "w", "dependencies": [], "status": "pending"},
            {"task_id": "2", "description": "发邮件", "agent_type": "local", "agent_target": "email", "dependencies": ["1"], "status": "pending"},
        ]
        state = {"messages": [], "user_request": "test", "task_plan": plan, "final_response": ""}
        result = await aggregate_node(state, model=model)
        assert len(result["final_response"]) > 10

    @pytest.mark.asyncio
    async def test_empty_plan_still_generates_reply(self):
        model = ScriptedChatModel(responses=[ai_text("你好,有什么可以帮你的?")])
        state = {"messages": [HumanMessage("你好")], "user_request": "test", "task_plan": [], "final_response": ""}
        result = await aggregate_node(state, model=model)
        assert len(result["final_response"]) > 3


class TestGraph:
    def test_builds_and_compiles(self):
        model = ScriptedChatModel()
        graph = build_main_agent(model)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_end_to_end_planning(self):
        model = ScriptedChatModel(responses=[
            ai_text("用户想要整理本周工作"),
            ai_text(SAMPLE_PLAN_JSON),
            ai_text("规划落地文档"),
            ai_text("开发落地文档"),
            ai_text("好的,我计划:1)分析代码 2)查询任务 3)生成周报并发送"),
        ])
        graph = build_main_agent(model)

        result = await graph.ainvoke({
            "messages": [HumanMessage("帮我整理本周工作")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })

        plan = result["task_plan"]
        assert len(plan) == 3
        assert plan[0]["agent_type"] == "codex"
        assert plan[2]["dependencies"] == ["1", "2"]
        assert len(result["final_response"]) > 10
