"""code_plan 子 agent 切片测试:code 任务展开为切片子任务,deps 正确,非 code 透传。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.main_agent.code_plan import code_plan_node

SLICE_JSON = """[
  {"step_id": "1", "description": "探查项目结构", "deps": [], "prompt": "先查看当前目录结构,列出文件"},
  {"step_id": "2", "description": "实现功能", "deps": ["1"], "prompt": "基于第1步发现的结构,实现功能X"},
  {"step_id": "3", "description": "补充测试", "deps": ["2"], "prompt": "为功能X写单元测试"}
]"""


def _state(plan: list[dict]) -> dict:
    return {"messages": [], "user_request": "", "task_plan": plan, "final_response": ""}


class TestCodePlanNode:
    @pytest.mark.asyncio
    async def test_slices_codex_cli_task(self):
        """codex_cli 任务展开为切片子任务,description=专属 prompt。"""
        model = ScriptedChatModel(responses=[ai_text(SLICE_JSON)])
        plan = [
            {"task_id": "1", "description": "实现一个计算器", "agent_type": "codex_cli",
             "agent_target": "workspace", "dependencies": [], "status": "pending"},
        ]
        result = await code_plan_node(_state(plan), model=model)
        new_plan = result["task_plan"]
        assert len(new_plan) == 3, f"应展开为 3 个切片,实际 {len(new_plan)}"
        # description 是专属 prompt 而非原始描述
        assert new_plan[0]["description"] == "先查看当前目录结构,列出文件"
        assert new_plan[2]["description"] == "为功能X写单元测试"
        # 切片间依赖:step 2 依赖 step 1(用全局 task_id)
        assert new_plan[1]["dependencies"] == [new_plan[0]["task_id"]]
        assert new_plan[2]["dependencies"] == [new_plan[1]["task_id"]]
        # 保留原始描述
        assert new_plan[0]["original_description"] == "实现一个计算器"

    @pytest.mark.asyncio
    async def test_non_code_task_passthrough(self):
        """非 codex_cli 任务原样透传,不改动。"""
        model = ScriptedChatModel(responses=[ai_text(SLICE_JSON)])
        plan = [
            {"task_id": "1", "description": "发邮件", "agent_type": "local",
             "agent_target": "email", "dependencies": [], "status": "pending"},
        ]
        result = await code_plan_node(_state(plan), model=model)
        assert result == {} or result["task_plan"] == plan

    @pytest.mark.asyncio
    async def test_mixed_keeps_non_code_and_slices_code(self):
        """混合计划:codex_cli 切片,local 保留,且 deps 映射正确。"""
        model = ScriptedChatModel(responses=[ai_text(SLICE_JSON)])
        plan = [
            {"task_id": "1", "description": "实现计算器", "agent_type": "codex_cli",
             "agent_target": "w", "dependencies": [], "status": "pending"},
            {"task_id": "2", "description": "发总结邮件", "agent_type": "local",
             "agent_target": "email", "dependencies": ["1"], "status": "pending"},
        ]
        result = await code_plan_node(_state(plan), model=model)
        new_plan = result["task_plan"]
        assert len(new_plan) == 4  # 3 切片 + 1 local
        # local 任务保留,依赖指向第一个切片
        local = [t for t in new_plan if t["agent_type"] == "local"]
        assert len(local) == 1
        slice_tasks = [t for t in new_plan if t["agent_type"] == "codex_cli"]
        # local 的依赖应指向切片链的最后一个(实现完成),或第一个切片
        # 这里 local 依赖原 codex 任务(id=1),被映射到切片链第一个
        first_slice_id = slice_tasks[0]["task_id"]
        assert local[0]["dependencies"] == [first_slice_id]

    @pytest.mark.asyncio
    async def test_slice_failure_keeps_original(self):
        """切片失败(planner 输出非法)时保留原任务。"""
        model = ScriptedChatModel(responses=[ai_text("不是 JSON 格式的回复")])
        plan = [
            {"task_id": "1", "description": "复杂任务", "agent_type": "codex_cli",
             "agent_target": "w", "dependencies": [], "status": "pending"},
        ]
        result = await code_plan_node(_state(plan), model=model)
        new_plan = result["task_plan"]
        assert len(new_plan) == 1
        assert new_plan[0]["description"] == "复杂任务"  # 原样保留
