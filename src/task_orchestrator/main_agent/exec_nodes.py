"""dispatch / monitor / replan 节点 + 图路由逻辑。

依赖处理策略:
- dispatch 提交"依赖已全部完成"的 pending → running
- monitor 轮询 running 收集结果,并把"依赖已完成的 pending"提升为 ready
- 路由:还有 running/ready → 回 dispatch 继续;有失败 → replan;否则 aggregate
- replan 带重试上限,防止"失败→重试→再失败"死循环
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import END

from task_orchestrator.main_agent.state import MainAgentState
from task_orchestrator.registry import AgentRegistry

logger = logging.getLogger("main_agent.exec")

# monitor 轮询间隔与整体超时
_POLL_INTERVAL = 0.2
_MONITOR_TIMEOUT = 180.0
# 单任务最大执行/审查重试次数:执行失败或审查不通过累计超过则放弃,防止死循环
_MAX_RETRIES = 3

_TERMINAL = ("completed", "failed", "canceled")


REVIEW_PROMPT = """你是子任务审查员。对比「子任务要求」与「执行结果」,判断子任务是否真正完成。

规则:
1. 结果缺失、明显不相关、格式不对、内容为空 → 不通过
2. 本地文件/Shell 任务: 确认操作已实际完成(如"已写入"、"已发送"、"已创建")即通过
3. 检索任务: 返回了实质内容即通过,不要求内容完全匹配
4. 只要输出一行:PASS  或  FAIL <简短原因>

示例:
PASS
PASS
FAIL 结果为空,没有给出检索内容
FAIL 结果是日程表,但要求是检索资料,不相关
"""


async def review_node(task: dict, *, model: BaseChatModel) -> tuple[bool, str]:
    """审查单个子任务:LLM 对比任务要求 vs 执行结果,返回 (是否通过, 原因)。"""
    result_text = task.get("result") or ""
    if not str(result_text).strip():
        return False, "执行结果为空"

    response = await model.ainvoke([
        SystemMessage(content=REVIEW_PROMPT),
        HumanMessage(content=f"子任务要求:{task.get('description', '')}\n执行结果:{result_text}"),
    ])
    verdict = str(response.content).strip()
    passed = verdict.upper().startswith("PASS")
    reason = "" if passed else (verdict[len("FAIL"):].strip() or "审查未通过")
    return passed, reason


async def dispatch_node(
    state: MainAgentState, *, registry: AgentRegistry
) -> dict:
    """遍历任务计划,提交依赖已就绪的任务到对应适配器。"""
    plan = state.get("task_plan", [])
    if not plan:
        return {}

    updated = []
    for task in plan:
        status = task.get("status", "pending")
        deps = task.get("dependencies", [])

        # 依赖已终止但失败/取消 → 本任务级联取消
        if status == "pending" and _any_dep_failed(deps, plan):
            task["status"] = "canceled"
            task["error"] = "依赖任务失败,无法执行"
            updated.append(task)
            continue

        # 依赖全部完成 → ready → 提交
        if status == "pending" and _all_deps_completed(deps, plan):
            task["status"] = "ready"
            status = "ready"

        if status == "ready":
            adapter = registry.get_by_type(task.get("agent_type", "local"))
            if adapter and adapter.is_available:
                try:
                    external_id = await adapter.submit(task)
                    task["status"] = "running"
                    task["external_id"] = external_id
                    task["error"] = None
                    logger.info("子任务已提交", extra={
                        "task_id": task["task_id"],
                        "agent": task["agent_type"],
                    })
                except Exception as exc:
                    task["status"] = "failed"
                    task["error"] = str(exc)
                    logger.error("子任务提交失败", extra={"task_id": task["task_id"], "error": str(exc)})
            else:
                task["status"] = "failed"
                task["error"] = f"Agent 类型 {task.get('agent_type')} 不可用"

        updated.append(task)

    return {"task_plan": updated}


async def monitor_node(
    state: MainAgentState, *, registry: AgentRegistry, model: BaseChatModel | None = None
) -> dict:
    """阻塞等待所有 running 任务终止,收集结果并逐任务审查;提升依赖已完成的 pending → ready。

    审查:adapter 返回 completed 后,若传入 model 则先用 LLM 对比"要求 vs 结果",
    通过才标 completed;不通过则记录审查不通过原因,累计重试超限即标失败。
    """
    import time as _time
    plan = state.get("task_plan", [])
    deadline = _time.monotonic() + _MONITOR_TIMEOUT

    while True:
        has_running = False
        for task in plan:
            if task.get("status") != "running":
                continue
            adapter = registry.get_by_type(task.get("agent_type", "local"))
            if not adapter:
                task["status"] = "completed"
                task["result"] = "完成"
                continue
            try:
                ext_id = task.get("external_id", "")
                task_status = await adapter.status(ext_id)
                # 边跑边同步进度(adapter 有 progress 方法时)
                if hasattr(adapter, "progress") and task_status == "running":
                    try:
                        prog = await adapter.progress(ext_id)
                        if prog:
                            task["progress"] = prog
                    except Exception:
                        pass
                # ask 模式等待人工介入(不算 running,monitor 结束,任务保留状态待展示)
                if task_status == "running" and hasattr(adapter, "is_waiting_approval"):
                    try:
                        if await adapter.is_waiting_approval(ext_id):
                            task["status"] = "waiting_approval"
                            task["error"] = "等待人工审批:codex 请求权限"
                            continue
                    except Exception:
                        pass
                if task_status == "completed":
                    result = await adapter.result(ext_id)
                    if result:
                        task["result"] = result
                    logger.info("子任务执行完成,进入审查", extra={"task_id": task["task_id"]})
                    passed, reason = True, ""
                    if model is not None:
                        passed, reason = await review_node(task, model=model)
                    if passed:
                        task["status"] = "completed"
                        task["error"] = None
                        logger.info("子任务审查通过", extra={"task_id": task["task_id"]})
                    else:
                        task["retry_count"] = task.get("retry_count", 0) + 1
                        if task["retry_count"] > _MAX_RETRIES:
                            # 需监控长任务:第三次审查不通过时,取 codex 当前进度作为结果
                            if task.get("requires_monitor") and hasattr(adapter, "progress"):
                                prog = await adapter.progress(ext_id)
                                task["result"] = prog or task.get("progress") or task.get("result")
                                task["status"] = "completed"
                                task["error"] = None
                                task["progress"] = prog
                                logger.info("需监控长任务按进度收尾", extra={
                                    "task_id": task["task_id"], "progress": (prog or "")[:80],
                                })
                            else:
                                task["status"] = "failed"
                                task["error"] = f"审查 {_MAX_RETRIES} 次未通过:{reason or '无原因'}"
                                logger.warning("子任务审查多次未通过", extra={
                                    "task_id": task["task_id"], "reason": reason,
                                })
                        else:
                            task["status"] = "failed"
                            task["error"] = f"审查不通过:{reason or '无原因'}"
                            logger.info("子任务审查不通过,待重试", extra={
                                "task_id": task["task_id"], "retry": task["retry_count"],
                            })
                elif task_status == "failed":
                    task["status"] = "failed"
                    task["error"] = task.get("error") or "远端执行失败"
                else:
                    has_running = True
            except Exception as exc:
                task["status"] = "failed"
                task["error"] = str(exc)

        # 依赖已完成的 pending → ready(下轮 dispatch 提交)
        for task in plan:
            if task.get("status") == "pending":
                deps = task.get("dependencies", [])
                if _all_deps_completed(deps, plan):
                    task["status"] = "ready"

        if not has_running:
            break
        if _time.monotonic() > deadline:
            for task in plan:
                if task.get("status") == "running":
                    task["status"] = "failed"
                    task["error"] = task.get("error") or "执行超时"
            logger.warning("子任务监控超时", extra={"timeout": _MONITOR_TIMEOUT})
            break
        await asyncio.sleep(_POLL_INTERVAL)

    return {"task_plan": plan}


def route_after_monitor(
    state: MainAgentState,
) -> Literal["aggregate_node", "replan_node", "dispatch", END]:
    """监控后路由:
    - 有 running / 刚就绪的 ready → 回 dispatch(继续提交)
    - 有待人工审批的任务(waiting_approval)→ 图暂停(返回 END,checkpoint 保存,等前端批准后续跑)
    - 全部终止且有失败(可重试)→ replan
    - 否则 → aggregate
    """
    plan = state.get("task_plan", [])
    has_active = any(
        t.get("status") in ("running", "ready") for t in plan
    )
    if has_active:
        return "dispatch"

    has_waiting = any(t.get("status") == "waiting_approval" for t in plan)
    if has_waiting:
        return END

    has_failed = any(t.get("status") == "failed" for t in plan)
    if has_failed:
        return "replan_node"
    return "aggregate_node"


REPLAN_PROMPT = """你是任务重规划专家。部分子任务执行失败,请决定如何处理。

规则:
1. 如果是 Agent 不可用导致的失败,尝试换一种 agent_type
2. 如果是业务逻辑错误,尝试修改任务描述后重试
3. 如果无法修复,将任务标记为取消(canceled)
4. 不要新增子任务,只修改现有任务的 agent_type/description/status
5. 回复格式:列出每个失败任务的处理方案,一行一个

示例回复:
task_1: agent_type 改为 local,重试
task_3: status 改为 canceled,无法修复
"""


async def replan_node(
    state: MainAgentState, *, model: BaseChatModel
) -> dict:
    """对失败任务进行重规划(带重试上限防死循环)。"""
    plan = state.get("task_plan", [])
    failed = [t for t in plan if t.get("status") == "failed"]

    if not failed:
        return {}

    failed_desc = "\n".join(
        f"{t['task_id']}: [{t['agent_type']}] {t['description']}, 错误:{t.get('error', '未知')}"
        for t in failed
    )

    response = await model.ainvoke([
        SystemMessage(content=REPLAN_PROMPT),
        HumanMessage(content=f"失败任务:\n{failed_desc}"),
    ])
    instruction = str(response.content).strip()
    logger.info("重规划决策", extra={"instruction": instruction[:200]})

    updated = []
    for task in plan:
        if task.get("status") != "failed":
            updated.append(task)
            continue

        tid = task["task_id"]
        task["retry_count"] = task.get("retry_count", 0) + 1
        over_limit = task["retry_count"] > _MAX_RETRIES

        action = None
        if f"task_{tid}:" in instruction.lower():
            line = [l for l in instruction.split("\n") if f"task_{tid}:" in l.lower()]
            if line:
                content = line[0].lower()
                if "canceled" in content or "取消" in content:
                    action = "cancel"
                elif "local" in content:
                    action = ("retry", "local")
                elif "codex" in content:
                    action = ("retry", "codex")
                elif "重试" in content or "retry" in content:
                    action = "retry"
                else:
                    action = "cancel"
            else:
                action = "cancel"

        if over_limit:
            task["status"] = "canceled"
            task["error"] = "重试次数超限,已放弃"
        elif action == "cancel":
            task["status"] = "canceled"
        elif isinstance(action, tuple):
            task["agent_type"] = action[1]
            task["status"] = "ready"
            task["error"] = None
        elif action == "retry":
            task["status"] = "ready"
            task["error"] = None
        else:
            task["status"] = "canceled"

        updated.append(task)

    return {"task_plan": updated, "messages": [response]}


def _all_deps_completed(deps: list[str], plan: list[dict]) -> bool:
    for dep_id in deps:
        dep_task = next((t for t in plan if t.get("task_id") == dep_id), None)
        if dep_task is None or dep_task.get("status") != "completed":
            return False
    return True


def _any_dep_failed(deps: list[str], plan: list[dict]) -> bool:
    for dep_id in deps:
        dep_task = next((t for t in plan if t.get("task_id") == dep_id), None)
        if dep_task is not None and dep_task.get("status") in ("failed", "canceled"):
            return True
    return False
