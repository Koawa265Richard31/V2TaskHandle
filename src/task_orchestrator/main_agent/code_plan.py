"""code planner 子 agent:把复杂 code 任务切片成多个子任务,并为每个生成专属提示词。

在 plan 之后、dispatch 之前运行。对 task_plan 中 agent_type=codex_cli 的任务,
用 asyncio 并行(子线程语义)调用 LLM 理解主任务 → 输出切片 JSON,展开为多个子任务:
- 每个切片子任务 task_id 重编号, dependencies 关联
- description 替换为发给 codex 的专属提示词(含任务上下文/约束/验收)
- 非 code 任务原样保留
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from task_orchestrator.main_agent.prompts import CODE_PLAN_PROMPT
from task_orchestrator.main_agent.state import MainAgentState

logger = logging.getLogger("main_agent.code_plan")

# 需要切片的 agent_type(仅真实本机 code agent;Mock/SDK codex 保持原样)
_SLICE_TYPES = {"codex_cli"}


async def code_plan_node(
    state: MainAgentState, *, model: BaseChatModel
) -> dict:
    """对 code 任务并行切片;无 code 任务时透传。"""
    plan = state.get("task_plan", [])
    if not plan:
        return {}

    code_tasks = [t for t in plan if t.get("agent_type") in _SLICE_TYPES]
    other_tasks = [t for t in plan if t.get("agent_type") not in _SLICE_TYPES]

    if not code_tasks:
        return {}  # 无 code 任务,原样透传

    # 并行(子线程)对每个 code 任务调 planner
    results = await asyncio.gather(
        *[_plan_one(task, model=model) for task in code_tasks],
        return_exceptions=True,
    )
    # code 任务旧 id → 切片结果
    code_task_result: dict[str, list[dict]] = {
        str(task.get("task_id")): result
        for task, result in zip(code_tasks, results)
        if not isinstance(result, Exception) and result
    }

    new_plan: list[dict] = []
    # 完整重编号:old_id → 第一个新 id。code 任务切片占多个 id,其余占 1 个。
    # 先为所有任务计算新 id 区间,保证非 code 任务依赖 code 任务时映射正确。
    id_map: dict[str, str] = {}
    next_id = 1

    # 第一阶段:规划每个任务的 id 区间,建映射
    layout: list[tuple[dict, int]] = []  # (task, 占位数量)
    for task in other_tasks:
        old_id = str(task.get("task_id", ""))
        id_map[old_id] = str(next_id)
        next_id += 1
        layout.append((task, 1))
    for task, result in zip(code_tasks, results):
        old_id = str(task.get("task_id", ""))
        if isinstance(result, Exception) or not result:
            id_map[old_id] = str(next_id)
            next_id += 1
            layout.append((task, 1))
        else:
            id_map[old_id] = str(next_id)
            next_id += len(result)
            layout.append((task, len(result)))

    # 第二阶段:按 layout 构造(非 code 原样,code 展开切片)
    cursor = 1
    for task, span in layout:
        old_id = str(task.get("task_id", ""))
        new_id = str(cursor)
        cursor += span
        if task.get("agent_type") in _SLICE_TYPES and span > 1:
            # 从 code_task_result 里取该 code 任务的切片
            result = code_task_result[task.get("task_id")]
            original = dict(task)
            base_deps = [id_map.get(d, d) for d in original.get("dependencies", [])]
            step_map: dict[str, str] = {}
            base_id = int(new_id)
            for offset, sl in enumerate(result):
                step_id = str(sl.get("step_id", ""))
                step_map[step_id] = str(base_id + offset)
            for i, sl in enumerate(result):
                new_task = dict(original)
                new_task["task_id"] = step_map[str(sl.get("step_id", ""))]
                prompt = sl.get("prompt") or sl.get("description") or original.get("description", "")
                new_task["description"] = prompt
                slice_deps = [step_map.get(str(d), str(d)) for d in sl.get("deps", [])]
                if i == 0:
                    slice_deps.extend(base_deps)
                new_task["dependencies"] = slice_deps
                new_task["original_description"] = original.get("description", "")
                new_task["slice_step"] = sl.get("step_id") or sl.get("description", "")[:40]
                new_plan.append(new_task)
        else:
            # 非 code 任务或切片失败:原样,重编号 + 映射 deps
            task["task_id"] = new_id
            task["dependencies"] = [id_map.get(d, d) for d in task.get("dependencies", [])]
            new_plan.append(task)

    logger.info("code 任务切片完成", extra={
        "code_tasks": len(code_tasks), "plan_after": len(new_plan),
    })
    return {"task_plan": new_plan}


async def _plan_one(task: dict, *, model: BaseChatModel) -> list[dict]:
    """单个 code 任务 → planner LLM → 切片列表。"""
    desc = task.get("description", "")
    try:
        response = await model.ainvoke([
            SystemMessage(content=CODE_PLAN_PROMPT),
            HumanMessage(content=f"任务:{desc}"),
        ])
        raw = str(response.content).strip()
        # 提取 JSON(可能被 code block 包裹)
        if "```" in raw:
            raw = _extract_json(raw)
        slices = json.loads(raw)
        if not isinstance(slices, list):
            raise ValueError(f"planner 输出不是数组: {raw[:100]}")
        # 归一化
        return [
            {
                "step_id": str(s.get("step_id", i + 1)),
                "description": s.get("description", ""),
                "deps": [str(d) for d in s.get("deps", [])],
                "prompt": s.get("prompt", ""),
            }
            for i, s in enumerate(slices)
            if isinstance(s, dict) and (s.get("description") or s.get("prompt"))
        ]
    except Exception as exc:
        logger.warning("单任务切片失败", extra={"task": desc[:50], "error": str(exc)})
        raise


def _extract_json(raw: str) -> str:
    lines = raw.split("\n")
    json_lines = []
    in_json = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_json = not in_json
            continue
        if in_json:
            json_lines.append(line)
    return "\n".join(json_lines).strip() or raw
