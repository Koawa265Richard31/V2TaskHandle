"""dispatch / monitor / replan 节点测试。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.exec_nodes import (
    dispatch_node,
    monitor_node,
    replan_node,
    review_node,
    route_after_monitor,
)
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry
from langchain_core.messages import HumanMessage


class MockMonitorAdapter(MockCodexAdapter):
    """带 progress/is_waiting_approval 的监控型 mock adapter。"""

    def __init__(self, progress_text: str | None = None, waiting: bool = False):
        super().__init__()
        self._prog = progress_text
        self._waiting = waiting
        self._first_running = True

    async def status(self, external_id: str) -> str:
        # 第一次返回 running(让 monitor 走进度同步/waiting 检测),之后 completed
        if self._first_running:
            self._first_running = False
            return "running"
        return "completed"

    async def progress(self, external_id: str) -> str | None:
        return self._prog

    async def is_waiting_approval(self, external_id: str) -> bool:
        return self._waiting


@pytest.fixture
def registry():
    r = AgentRegistry()
    r.register(MockCodexAdapter(), "codex")
    r.register(LocalAdapter(enabled_tools=["shell", "file"]), "local")
    return r


@pytest.fixture
def sample_plan():
    return [
        {"task_id": "1", "description": "分析代码", "agent_type": "codex",
         "agent_target": "workspace_write", "dependencies": [], "status": "pending"},
        {"task_id": "2", "description": "发邮件", "agent_type": "local",
         "agent_target": "email", "dependencies": ["1"], "status": "pending"},
    ]


class TestDispatchNode:
    @pytest.mark.asyncio
    async def test_dispatches_ready_tasks(self, registry, sample_plan):
        state = {"messages": [], "user_request": "", "task_plan": sample_plan, "final_response": ""}
        result = await dispatch_node(state, registry=registry)
        plan = result["task_plan"]
        assert plan[0]["status"] == "running"
        assert "external_id" in plan[0]
        assert plan[1]["status"] == "pending"  # dep not done

    @pytest.mark.asyncio
    async def test_unavailable_agent_fails(self, sample_plan):
        r = AgentRegistry()  # empty registry
        sample_plan[0]["status"] = "ready"
        state = {"messages": [], "user_request": "", "task_plan": sample_plan, "final_response": ""}
        result = await dispatch_node(state, registry=r)
        assert result["task_plan"][0]["status"] == "failed"


class TestMonitorNode:
    @pytest.mark.asyncio
    async def test_completes_running_tasks(self, registry):
        plan = [
            {"task_id": "1", "description": "test", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=registry)
        assert result["task_plan"][0]["status"] == "completed"


class TestReviewNode:
    @pytest.mark.asyncio
    async def test_pass(self):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("PASS"))])
        task = {"description": "检索糖尿病指南", "result": "查到了指南"}
        passed, reason = await review_node(task, model=model)
        assert passed is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_fail(self):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 结果为空"))])
        task = {"description": "检索资料", "result": "无"}
        passed, reason = await review_node(task, model=model)
        assert passed is False
        assert "结果为空" in reason

    @pytest.mark.asyncio
    async def test_empty_result(self):
        model = ScriptedChatModel()
        task = {"description": "x", "result": "   "}
        passed, reason = await review_node(task, model=model)
        assert passed is False
        assert "为空" in reason

    @pytest.mark.asyncio
    async def test_fail_reason_extraction(self):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 格式不对,缺少表格"))])
        task = {"description": "生成表格", "result": "只有一段话"}
        passed, reason = await review_node(task, model=model)
        assert passed is False
        assert "表格" in reason


class TestMonitorReview:
    @pytest.mark.asyncio
    async def test_review_pass_marks_completed(self, registry):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("PASS"))])
        plan = [
            {"task_id": "1", "description": "检索资料", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=registry, model=model)
        assert result["task_plan"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_review_fail_marks_failed_and_retries(self, registry):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 内容不相关"))])
        plan = [
            {"task_id": "1", "description": "检索资料", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=registry, model=model)
        task = result["task_plan"][0]
        assert task["status"] == "failed"
        assert task["retry_count"] == 1
        assert "审查不通过" in task["error"]

    @pytest.mark.asyncio
    async def test_review_fail_three_times_marks_give_up(self, registry):
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 始终不对"))])
        plan = [
            {"task_id": "1", "description": "检索资料", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id", "retry_count": 3},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=registry, model=model)
        task = result["task_plan"][0]
        assert task["status"] == "failed"
        assert task["retry_count"] == 4
        assert "3 次未通过" in task["error"]

    @pytest.mark.asyncio
    async def test_no_model_skips_review(self, registry):
        plan = [
            {"task_id": "1", "description": "test", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=registry)  # model=None
        assert result["task_plan"][0]["status"] == "completed"


class TestMonitorReviewProgress:
    @pytest.mark.asyncio
    async def test_requires_monitor_third_fail_uses_progress(self):
        """需监控任务第 3 次审查不通过 → 用 codex 进度文本收尾为 completed。"""
        r = AgentRegistry()
        r.register(MockMonitorAdapter(progress_text="已创建 3 个文件,还剩 1 个模块待改"), "codex")
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 尚未完成"))])
        plan = [
            {"task_id": "1", "description": "重构模块", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id", "retry_count": 3, "requires_monitor": True},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=r, model=model)
        task = result["task_plan"][0]
        assert task["status"] == "completed"
        assert "已创建 3 个文件" in (task.get("result") or "")
        assert task.get("progress")

    @pytest.mark.asyncio
    async def test_requires_monitor_running_syncs_progress(self):
        """需监控任务 running 期间轮询到进度,写入 task['progress']。"""
        r = AgentRegistry()
        r.register(MockMonitorAdapter(progress_text="分析代码结构中"), "codex")
        plan = [
            {"task_id": "1", "description": "分析", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id", "requires_monitor": True},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=r)  # model=None → completed
        task = result["task_plan"][0]
        assert task.get("progress") == "分析代码结构中"

    @pytest.mark.asyncio
    async def test_waiting_approval_marks_status(self):
        """ask 模式 adapter 报告等待人工介入 → 任务标 waiting_approval。"""
        r = AgentRegistry()
        r.register(MockMonitorAdapter(waiting=True), "codex")
        plan = [
            {"task_id": "1", "description": "写文件", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id", "requires_monitor": True},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=r)
        task = result["task_plan"][0]
        assert task["status"] == "waiting_approval"
        assert "审批" in task["error"]

    @pytest.mark.asyncio
    async def test_normal_task_third_fail_still_failed(self):
        """非需监控任务第 3 次审查不通过 → 仍标 failed(不按进度收尾)。"""
        r = AgentRegistry()
        r.register(MockMonitorAdapter(progress_text="进度X"), "codex")
        model = ScriptedChatModel(rules=[("执行结果", ai_text("FAIL 不对"))])
        plan = [
            {"task_id": "1", "description": "短任务", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "running",
             "external_id": "mock_id", "retry_count": 3, "requires_monitor": False},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await monitor_node(state, registry=r, model=model)
        task = result["task_plan"][0]
        assert task["status"] == "failed"
        assert "未通过" in task["error"]


class TestReplanNode:
    @pytest.mark.asyncio
    async def test_retries_failed_task(self):
        model = ScriptedChatModel(rules=[("失败", ai_text(
            "task_1: agent_type 改为 local,重试\n"
        ))])
        plan = [
            {"task_id": "1", "description": "分析代码", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "failed",
             "error": "Codex 不可用"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await replan_node(state, model=model)
        assert result["task_plan"][0]["status"] == "ready"
        assert result["task_plan"][0]["agent_type"] == "local"

    @pytest.mark.asyncio
    async def test_cancels_unfixable_task(self):
        model = ScriptedChatModel(rules=[("失败", ai_text(
            "task_1: status 改为 canceled,无法修复\n"
        ))])
        plan = [
            {"task_id": "1", "description": "broken", "agent_type": "codex",
             "agent_target": "w", "dependencies": [], "status": "failed",
             "error": "未知错误"},
        ]
        state = {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}
        result = await replan_node(state, model=model)
        assert result["task_plan"][0]["status"] == "canceled"


class TestFullGraph:
    def test_compiles(self, registry):
        model = ScriptedChatModel()
        graph = build_main_agent(model, registry)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_end_to_end_simple(self, registry):
        """FakeLLM 驱动:understand → plan → dispatch → monitor → aggregate"""
        model = ScriptedChatModel(responses=[
            ai_text("用户想要分析代码"),
            ai_text('[{"task_id":"1","description":"分析代码","agent_type":"codex","agent_target":"workspace_write","dependencies":[]}]'),
            ai_text("PASS"),
            ai_text("好的,已提交代码分析任务"),
        ])
        graph = build_main_agent(model, registry)

        result = await graph.ainvoke({
            "messages": [HumanMessage("帮我分析代码")],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
        })

        plan = result["task_plan"]
        assert len(plan) >= 1
        # 应该已经 dispatched + monitored → completed
        assert plan[0]["status"] in ("running", "completed")


class TestRouteAfterMonitorApproval:
    def _state(self, plan):
        return {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}

    def test_waiting_approval_stops_graph(self):
        """waiting_approval 任务存在时图应暂停(返回 END),不聚合不 replan。"""
        from langgraph.graph import END
        plan = [
            {"task_id": "1", "status": "waiting_approval", "agent_type": "codex_cli",
             "error": "等待人工审批"},
        ]
        assert route_after_monitor(self._state(plan)) == END

    def test_no_waiting_goes_aggregate(self):
        """无 waiting_approval 且全部完成时走 aggregate。"""
        plan = [
            {"task_id": "1", "status": "completed", "agent_type": "local"},
        ]
        assert route_after_monitor(self._state(plan)) == "aggregate_node"

    def test_waiting_plus_running_goes_dispatch(self):
        """waiting_approval 与其他 running 并存时继续 dispatch(等其余任务完成)。"""
        plan = [
            {"task_id": "1", "status": "waiting_approval", "agent_type": "codex_cli"},
            {"task_id": "2", "status": "running", "agent_type": "local"},
        ]
        assert route_after_monitor(self._state(plan)) == "dispatch"

    def test_waiting_plus_failed_waits_not_replan(self):
        """waiting_approval 与 failed 并存:优先暂停(等审批),不触发 replan。"""
        from langgraph.graph import END
        plan = [
            {"task_id": "1", "status": "waiting_approval", "agent_type": "codex_cli"},
            {"task_id": "2", "status": "failed", "agent_type": "local"},
        ]
        assert route_after_monitor(self._state(plan)) == END
