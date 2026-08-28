"""docs_node / evaluate_node:落地文档与整体评估报告(项目原型流水线)。"""
from __future__ import annotations

import asyncio

from task_orchestrator.common.llm import ScriptedChatModel
from task_orchestrator.main_agent.nodes import docs_node, evaluate_node


def _run(coro):
    return asyncio.run(coro)


def _fake(text: str, tier: str = "") -> ScriptedChatModel:
    return ScriptedChatModel(default_response=text, tier=tier)


def _state(tasks=None, documents=None, evaluation="", user_request="做个倒计时工具"):
    return {
        "messages": [],
        "user_request": user_request,
        "task_plan": tasks or [],
        "final_response": "",
        "documents": documents or {},
        "evaluation": evaluation,
    }


def test_docs_node_generates_and_writes(tmp_path):
    tasks = [{"task_id": "1", "description": "写规划", "agent_type": "implementer"}]
    state = _state(tasks)
    planner = _fake("规划文档正文", tier="planner")
    architect = _fake("开发文档正文", tier="architect")
    out = _run(docs_node(state, planner_model=planner, architect_model=architect,
                         project_dir=tmp_path))

    assert out["documents"]["plan"] == "规划文档正文"
    assert out["documents"]["dev"] == "开发文档正文"
    assert (tmp_path / "plan.md").read_text(encoding="utf-8") == "规划文档正文"
    assert (tmp_path / "dev.md").read_text(encoding="utf-8") == "开发文档正文"
    assert planner.tier == "planner" and architect.tier == "architect"


def test_docs_node_skips_when_no_tasks(tmp_path):
    out = _run(docs_node(_state([]), planner_model=_fake("p"), architect_model=_fake("a"),
                         project_dir=tmp_path))
    assert out == {}
    assert not list(tmp_path.glob("*.md"))


def test_evaluate_node_report_and_file(tmp_path):
    tasks = [
        {"task_id": "1", "description": "实现A", "agent_type": "implementer",
         "status": "completed", "result": "A 的产物"},
        {"task_id": "2", "description": "实现B", "agent_type": "implementer",
         "status": "failed", "result": "", "error": "审查未通过"},
    ]
    state = _state(tasks, documents={"dev": "## 验收\n- A: 能运行\n- B: 有输出"})
    evaluator = _fake("### 差距\n- B 未完成\n- A 未验证\n不包括上线结论", tier="evaluator")
    out = _run(evaluate_node(state, model=evaluator, project_dir=tmp_path))

    assert out["evaluation"]
    assert (tmp_path / "evaluation.md").read_text(encoding="utf-8") == out["evaluation"]
    # 输入里包含验收标准与执行结果
    # evaluator 只调用一次
    assert evaluator.tier == "evaluator"


def test_evaluate_node_skips_when_empty(tmp_path):
    out = _run(evaluate_node(_state([]), model=_fake("报告"), project_dir=tmp_path))
    assert out == {}
    assert not (tmp_path / "evaluation.md").exists()


def test_evaluate_node_includes_acceptance_and_results():
    captured: list[str] = []

    class CapModel(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            captured.append(str(messages[-1].content))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    tasks = [{"task_id": "1", "description": "装页面", "agent_type": "implementer",
              "status": "completed", "result": "页面完成"}]
    state = _state(tasks, documents={"dev": "验收:页面可打开"})
    _run(evaluate_node(state, model=CapModel(default_response="报告"), project_dir=None))
    assert len(captured) == 1
    assert "验收:页面可打开" in captured[0]
    assert "页面完成" in captured[0]