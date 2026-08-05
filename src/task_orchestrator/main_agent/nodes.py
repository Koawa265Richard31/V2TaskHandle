"""Main Agent 节点:understand / plan / aggregate。"""
from __future__ import annotations

import json
import logging
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from task_orchestrator.main_agent.prompts import (
    UNDERSTAND_PROMPT,
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
