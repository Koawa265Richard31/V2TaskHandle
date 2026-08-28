"""Main Agent 完整图装配:understand → plan → docs → code_plan → dispatch → monitor → [replan|aggregate] → evaluate。

分层模型(models):{tier: BaseChatModel},来自 build_tier_models()。
- planner:    understand / plan / code_plan / replan / aggregate
- architect:  docs(开发落地文档)
- implementer: LlmAdapter 内部使用(便宜模型执行切片)
- reviewer:   monitor(逐片审查)
- evaluator:  evaluate(整体评估报告)
未配置的档位回退到传入的 model(单模型模式,行为与旧版一致)。
"""
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
    docs_node,
    evaluate_node,
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


def _pick(models: dict[str, BaseChatModel] | None, tier: str, fallback: BaseChatModel) -> BaseChatModel:
    """取某档位模型;models 为 None 或缺少该档位时回退 fallback。"""
    if models:
        return models.get(tier, fallback)
    return fallback


def build_main_agent(
    model: BaseChatModel,
    registry: AgentRegistry | None = None,
    checkpointer=None,
    role: str = "leader",
    extra_context: str = "",
    models: dict[str, BaseChatModel] | None = None,
    project_dir=None,
):
    """构建 Main Agent 的完整 StateGraph。

    role 决定规划器的能力提示:leader 可向组员下发;member 只能执行本地任务。
    extra_context 用于在 agents_info 之外注入额外提示(如 retrieval adapter connect 状态更新)。
    models 为分层模型字典 {tier: BaseChatModel}(见模块 docstring);None 时全部回退 model。
    project_dir 为项目原型产物落盘目录(plan.md/dev.md/evaluation.md)。
    """
    graph = StateGraph(MainAgentState)
    agents_info = (registry.agents_summary() if registry else "") + "\n" + extra_context
    if role == "member":
        agents_info = (agents_info + "\n" + MEMBER_CAPABILITY_NOTE).strip() if agents_info else MEMBER_CAPABILITY_NOTE
    else:
        agents_info = (agents_info + "\n" + leader_capability_prompt()).strip() if agents_info else leader_capability_prompt()

    planner = _pick(models, "planner", model)
    architect = _pick(models, "architect", model)
    reviewer = _pick(models, "reviewer", model)
    evaluator = _pick(models, "evaluator", model)

    async def _understand(state: MainAgentState) -> dict:
        return await understand_node(state, model=planner)

    async def _plan(state: MainAgentState) -> dict:
        return await plan_node(state, model=planner, agents_info=agents_info)

    async def _docs(state: MainAgentState) -> dict:
        return await docs_node(
            state,
            planner_model=planner,
            architect_model=architect,
            project_dir=project_dir,
        )

    async def _code_plan(state: MainAgentState) -> dict:
        return await code_plan_node(state, model=planner)

    async def _dispatch(state: MainAgentState) -> dict:
        return await dispatch_node(state, registry=registry) if registry else {}

    async def _monitor(state: MainAgentState) -> dict:
        return await monitor_node(state, registry=registry, model=reviewer) if registry else {}

    async def _replan(state: MainAgentState) -> dict:
        return await replan_node(state, model=planner)

    async def _aggregate(state: MainAgentState) -> dict:
        return await aggregate_node(state, model=planner)

    async def _evaluate(state: MainAgentState) -> dict:
        return await evaluate_node(state, model=evaluator, project_dir=project_dir)

    graph.add_node("understand", _understand)
    graph.add_node("plan", _plan)
    graph.add_node("docs", _docs)
    graph.add_node("code_plan", _code_plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("monitor", _monitor)
    graph.add_node("replan", _replan)
    graph.add_node("aggregate", _aggregate)
    graph.add_node("evaluate", _evaluate)

    graph.add_edge(START, "understand")
    graph.add_edge("understand", "plan")
    graph.add_conditional_edges("plan", route_after_plan, {
        "aggregate_node": "docs",
        END: END,
    })
    graph.add_edge("docs", "code_plan")
    graph.add_edge("code_plan", "dispatch")
    graph.add_edge("dispatch", "monitor")
    graph.add_conditional_edges("monitor", route_after_monitor, {
        "aggregate_node": "aggregate",
        "replan_node": "replan",
        "dispatch": "dispatch",
        END: END,
    })
    graph.add_edge("replan", "dispatch")
    graph.add_edge("aggregate", "evaluate")
    graph.add_edge("evaluate", END)

    return graph.compile(checkpointer=checkpointer)