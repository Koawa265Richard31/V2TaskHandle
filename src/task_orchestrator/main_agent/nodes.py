"""Main Agent 节点:understand / plan / aggregate。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from task_orchestrator.main_agent.prompts import (
    UNDERSTAND_PROMPT,
    PLAN_DOC_PROMPT,
    DEV_DOC_PROMPT,
    EVALUATE_PROMPT,
    plan_prompt_with_context,
)
from task_orchestrator.main_agent.state import MainAgentState, SubTask

logger = logging.getLogger("main_agent.nodes")


async def understand_node(
    state: MainAgentState, *, model: BaseChatModel
) -> dict:
    """分析用户意图,提取核心目标。"""
    messages = state["messages"]
    user_text = messages[-1].content if messages else ""
    content = str(user_text)

    response = await model.ainvoke([
        SystemMessage(content=UNDERSTAND_PROMPT),
        HumanMessage(content=content),
    ])
    summary = str(response.content).strip()
    logger.info("意图分析完成", extra={"summary": summary[:120]})

    return {
        "user_request": summary,
        "messages": [response],
    }


async def plan_node(
    state: MainAgentState, *, model: BaseChatModel, agents_info: str = ""
) -> dict:
    """将用户目标分解为子任务计划。"""
    goal = state.get("user_request", "")
    prompt = plan_prompt_with_context(agents_info)

    response = await model.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"用户目标:{goal}"),
    ])
    raw = str(response.content).strip()

    # 提取 JSON（可能被 markdown code block 包裹）
    if "```" in raw:
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
        raw = "\n".join(json_lines).strip()
    else:
        raw = raw.strip()

    try:
        tasks_raw = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("计划 JSON 解析失败", extra={"raw": raw[:200]})
        return {
            "task_plan": [],
            "messages": [response],
        }

    # 校验每个任务
    task_plan = []
    for item in tasks_raw:
        try:
            task = SubTask.from_dict(item)
            task_plan.append(task.to_dict())
        except Exception:
            logger.warning("跳过无效子任务", extra={"item": item})

    logger.info("任务计划生成完成", extra={"task_count": len(task_plan)})

    return {
        "task_plan": task_plan,
        "messages": [response],
    }


def _task_plan_summary(tasks: list[dict]) -> str:
    """把任务计划压成给文档/评估环节看的一行一任务摘要。"""
    lines = []
    for t in tasks:
        deps = f" (依赖: {', '.join(t['dependencies'])})" if t.get("dependencies") else ""
        lines.append(f"{t['task_id']}. [{t.get('agent_type')}] {t['description']}{deps}")
    return "\n".join(lines)


async def docs_node(
    state: MainAgentState,
    *,
    planner_model: BaseChatModel,
    architect_model: BaseChatModel,
    project_dir=None,
) -> dict:
    """项目原型流水线:基于任务计划生成「规划落地文档」(planner)与「开发落地文档」(architect)。

    文档写入 state["documents"],若有 project_dir 则落盘 plan.md / dev.md。
    无任务(纯对话)时跳过。
    """
    tasks = state.get("task_plan", [])
    if not tasks:
        return {}
    goal = state.get("user_request", "")
    task_summary = _task_plan_summary(tasks)

    plan_doc = await planner_model.ainvoke([
        SystemMessage(content=PLAN_DOC_PROMPT),
        HumanMessage(content=f"用户原始构想:\n{goal}\n\n任务计划:\n{task_summary}"),
    ])
    plan_text = str(plan_doc.content).strip()

    dev_doc = await architect_model.ainvoke([
        SystemMessage(content=DEV_DOC_PROMPT),
        HumanMessage(
            content=f"规划落地文档:\n{plan_text}\n\n任务计划:\n{task_summary}"
        ),
    ])
    dev_text = str(dev_doc.content).strip()
    logger.info("落地文档生成完成", extra={
        "plan_chars": len(plan_text), "dev_chars": len(dev_text),
    })

    if project_dir:
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "plan.md").write_text(plan_text, encoding="utf-8")
        (project_dir / "dev.md").write_text(dev_text, encoding="utf-8")

    # 注意:文档是"工件",不追加进 messages(避免 A2A 执行器把最后一条消息当答复回传)
    return {"documents": {"plan": plan_text, "dev": dev_text}}


async def evaluate_node(
    state: MainAgentState, *, model: BaseChatModel, project_dir=None
) -> dict:
    """项目原型流水线:整体评估报告(evaluator)。

    只对照验收标准列差距与不确定性,明确不做"能否上线"结论;
    报告写入 state["evaluation"],有 project_dir 时落盘 evaluation.md。
    无任务也无文档(纯对话)时跳过。
    """
    tasks = state.get("task_plan", [])
    documents = state.get("documents") or {}
    if not tasks and not documents:
        return {}

    dev_doc = documents.get("dev", "")
    results_lines = []
    for t in tasks:
        status = t.get("status", "pending")
        result = (t.get("result") or "")[:500]
        results_lines.append(
            f"- {t['task_id']} [{t.get('agent_type')}] {t['description']}\n"
            f"  状态:{status} 结果:{result}"
        )
    checkpoints = (
        "开发文档验收标准:\n" + dev_doc
        if dev_doc else "开发文档未生成(无验收标准可对照)"
    )
    prompt = (
        "用户原始构想:\n" + (state.get("user_request", "") or "") +
        "\n\n" + checkpoints +
        "\n\n切片执行结果:\n" + "\n".join(results_lines)
    )
    response = await model.ainvoke([
        SystemMessage(content=EVALUATE_PROMPT),
        HumanMessage(content=prompt),
    ])
    report = str(response.content).strip()
    logger.info("整体评估报告生成完成", extra={"chars": len(report)})

    if project_dir:
        project_dir = Path(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "evaluation.md").write_text(report, encoding="utf-8")

    # 评估报告是"工件",不追加进 messages(避免 A2A 执行器把最后一条消息当答复回传)
    return {"evaluation": report}


async def aggregate_node(
    state: MainAgentState, *, model: BaseChatModel
) -> dict:
    """汇总计划结果或生成对话回复。"""
    tasks = state.get("task_plan", [])

    if not tasks:
        # 无任务:可能是闲聊,直接用 LLM 回复
        user_msg = state["messages"][-1].content if state.get("messages") else ""
        response = await model.ainvoke([
            SystemMessage(content="你是个人任务助手。用户的消息看起来不是任务请求,请用中文自然简短回复。"),
            HumanMessage(content=str(user_msg)),
        ])
        return {
            "final_response": str(response.content).strip(),
            "messages": [response],
        }

    lines = ["好的,我将按以下计划执行:\n"]
    for t in tasks:
        deps = f" (依赖: {', '.join(t['dependencies'])})" if t.get("dependencies") else ""
        lines.append(
            f"{t['task_id']}. [{t['agent_type']}] {t['description']}{deps}"
        )
    response_text = "\n".join(lines)

    response = await model.ainvoke([
        SystemMessage(content="将任务计划用中文简要告知用户,自然一点。"),
        HumanMessage(content=response_text),
    ])
    return {
        "final_response": str(response.content).strip(),
        "messages": [response],
    }


def route_after_plan(state: MainAgentState) -> Literal["aggregate_node", END]:
    """计划完成后:始终进入 aggregate（无任务时生成对话回复,有任务时生成执行摘要）。"""
    return "aggregate_node"
