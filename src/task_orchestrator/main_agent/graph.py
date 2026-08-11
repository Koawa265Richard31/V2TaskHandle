"""Main Agent 完整图装配:understand → plan → dispatch → monitor → [replan|aggregate]。"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from task_orchestrator.main_agent.exec_nodes import (
    dispatch_node,
    monitor_node,
    replan_node,
    route_after_monitor,
)
from task_orchestrator.main_agent.code_plan import code_plan_node
from task_orchestrator.main_agent.nodes import (
    aggregate_node,
    plan_node,
    route_after_plan,
    understand_node,
)
from task_orchestrator.main_agent.prompts import (
    MEMBER_CAPABILITY_NOTE,
    leader_capability_prompt,
)
from task_orchestrator.main_agent.state import MainAgentState
from task_orchestrator.registry import AgentRegistry


def build_main_agent(
    model: BaseChatModel,
    registry: AgentRegistry | None = None,
    checkpointer=None,
    role: str = "leader",
    extra_context: str = "",
):
    """构建 Main Agent 的完整 StateGraph。

    role 决定规划器的能力提示:leader 可向组员下发;member 只能执行本地任务。
    extra_context 用于在 agents_info 之外注入额外提示(如 retrieval adapter connect 状态更新)。
    """
    graph = StateGraph(MainAgentState)
    agents_info = (registry.agents_summary() if registry else "") + "\n" + extra_context
    if role == "member":
        agents_info = (agents_info + "\n" + MEMBER_CAPABILITY_NOTE).strip() if agents_info else MEMBER_CAPABILITY_NOTE
    else:
        agents_info = (agents_info + "\n" + leader_capability_prompt()).strip() if agents_info else leader_capability_prompt()

    async def _understand(state: MainAgentState) -> dict:
        return await understand_node(state, model=model)

    async def _plan(state: MainAgentState) -> dict:
        return await plan_node(state, model=model, agents_info=agents_info)

    async def _code_plan(state: MainAgentState) -> dict:
        return await code_plan_node(state, model=model)

    async def _dispatch(state: MainAgentState) -> dict:
        return await dispatch_node(state, registry=registry) if registry else {}

    async def _monitor(state: MainAgentState) -> dict:
        return await monitor_node(state, registry=registry, model=model) if registry else {}

    async def _replan(state: MainAgentState) -> dict:
        return await replan_node(state, model=model)

    async def _aggregate(state: MainAgentState) -> dict:
        return await aggregate_node(state, model=model)

    graph.add_node("understand", _understand)
    graph.add_node("plan", _plan)
    graph.add_node("code_plan", _code_plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("monitor", _monitor)
    graph.add_node("replan", _replan)
    graph.add_node("aggregate", _aggregate)

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "plan")
    graph.add_conditional_edges("plan", route_after_plan, {
        "aggregate_node": "code_plan",
        END: END,
    })
    graph.add_edge("code_plan", "dispatch")
    graph.add_edge("dispatch", "monitor")
    graph.add_conditional_edges("monitor", route_after_monitor, {
        "aggregate_node": "aggregate",
        "replan_node": "replan",
        "dispatch": "dispatch",
        END: END,
    })
    graph.add_edge("replan", "dispatch")
    graph.add_edge("aggregate", END)

    return graph.compile(checkpointer=checkpointer)
