"""分层模型流水线集成测试:planner→architect→implementer→reviewer→evaluator 全链路路由。

全部用 fake 档位模型,断言:
- implementer 切片由「implementer 档」模型执行(reviewer 档不被误用)
- reviewer 档做逐片审查
- evaluator 档生成评估报告
- 落地文档与评估报告落盘 project_dir
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage

from task_orchestrator.api.server import build_registry
from task_orchestrator.common.config import Settings
from task_orchestrator.common.llm import ScriptedChatModel
from task_orchestrator.main_agent.graph import build_main_agent

PLAN_JSON = json.dumps([
    {
        "task_id": "1",
        "description": "写产品说明书片段",
        "agent_type": "implementer",
        "agent_target": "",
        "dependencies": [],
    },
], ensure_ascii=False)


def _tier_models(replan_text: str | None = None) -> dict[str, ScriptedChatModel]:
    """每档独立 fake 模型;planner 按调用顺序:understand→plan→规划文档→[replan]→汇总。"""
    planner_responses = [
        AIMessage(content="用户想要一个番茄钟命令行工具"),
        AIMessage(content=PLAN_JSON),
        AIMessage(content="## 规划\n做一个番茄钟命令行原型"),
    ]
    if replan_text:
        planner_responses.append(AIMessage(content=replan_text))
    planner_responses.append(AIMessage(content="原型已完成,固化总结"))
    return {
        "planner": ScriptedChatModel(responses=planner_responses, tier="planner"),
        "architect": ScriptedChatModel(
            default_response="## 开发文档\n**验收**:切片1 输出说明书含功能列表", tier="architect"),
        "implementer": ScriptedChatModel(
            default_response="IMPLEM_V3_DELIVERABLE", tier="implementer"),
        "reviewer": ScriptedChatModel(default_response="PASS", tier="reviewer"),
        "evaluator": ScriptedChatModel(
            default_response="## 评估\n- 切片1已交付未验证\n- 差距:无测试", tier="evaluator"),
    }


def _run(coro):
    return asyncio.run(coro)


def test_tiered_pipeline_full_flow(tmp_path):
    settings = Settings(
        llm_provider="fake",
        data_dir=tmp_path / "data",
        model_tiers_json="[]",  # 分层模型由测试直接注入,不走配置
    )
    model = ScriptedChatModel(default_response="(fallback)", tier="")
    models = _tier_models()

    registry = build_registry(model, role="leader", settings=settings, tier_models=models)
    graph = build_main_agent(
        model, registry, role="leader", models=models,
        project_dir=tmp_path / "proj",
    )

    result = _run(graph.ainvoke(
        {
            "messages": [],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
            "documents": {},
            "evaluation": "",
        },
        {"configurable": {"thread_id": "t1"}},
    ))

    # 1) implementer 档执行切片,结果来自 implementer 模型(而非 reviewer)
    tasks = result["task_plan"]
    assert tasks, "应有 1 个切片任务"
    done = [t for t in tasks if t.get("status") == "completed"]
    assert done, f"切片应完成: {tasks}"
    assert done[0]["result"] == "IMPLEM_V3_DELIVERABLE"

    # 2) 落地文档由 planner/architect 档生成并落盘
    docs = result["documents"]
    assert "## 规划" in docs["plan"]
    assert "## 开发文档" in docs["dev"]
    assert (tmp_path / "proj" / "plan.md").read_text(encoding="utf-8") == docs["plan"]
    assert (tmp_path / "proj" / "dev.md").read_text(encoding="utf-8") == docs["dev"]

    # 3) evaluator 档生成评估报告并落盘
    assert "## 评估" in result["evaluation"]
    assert (tmp_path / "proj" / "evaluation.md").read_text(encoding="utf-8") == result["evaluation"]

    # 4) implementer 适配器已注册且可用
    adapter = registry.get_by_type("implementer")
    assert adapter is not None and adapter.is_available


def test_tiered_pipeline_review_fail_then_retry(tmp_path):
    """reviewer 档先 FAIL 再 PASS:验证审查门禁走的是 reviewer 档(审查标注不通过→重试→通过)。"""
    settings = Settings(llm_provider="fake", data_dir=tmp_path / "data")
    model = ScriptedChatModel(default_response="(fallback)", tier="")
    models = _tier_models(replan_text="task_1: 重试")
    # 审查第一次 FAIL,第二次 PASS
    models["reviewer"] = ScriptedChatModel(responses=[
        AIMessage(content="FAIL 结果不完整"),
        AIMessage(content="PASS"),
    ], tier="reviewer")

    registry = build_registry(model, role="leader", settings=settings, tier_models=models)
    graph = build_main_agent(model, registry, role="leader", models=models,
                             project_dir=tmp_path / "proj")

    result = _run(graph.ainvoke(
        {"messages": [], "user_request": "", "task_plan": [],
         "final_response": "", "documents": {}, "evaluation": ""},
        {"configurable": {"thread_id": "t2"}},
    ))

    # 审查不通过→重试(第二次评审通过)→completed
    done = [t for t in result["task_plan"] if t.get("status") == "completed"]
    assert done, f"重试后应完成: {result['task_plan']}"
    assert done[0]["retry_count"] >= 1


def test_cli_parser_subcommands():
    from task_orchestrator.cli.__main__ import _build_parser

    p = _build_parser()
    ns = p.parse_args(["chat", "做一个小工具", "--role", "member"])
    assert ns.command == "chat"
    assert ns.message == "做一个小工具"
    assert ns.role == "member"

    ns2 = p.parse_args(["serve", "--port", "9999"])
    assert ns2.command == "serve"
    assert ns2.port == 9999

    ns3 = p.parse_args([])  # 不传子命令 → 默认 serve(向后兼容)
    assert ns3.command is None