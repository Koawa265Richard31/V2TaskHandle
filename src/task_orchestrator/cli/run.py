"""命令行运行器:跑「项目原型流水线」并在控制台打印进度与产物路径。

流程:理解 → 规划 → 落地文档(plan.md/dev.md) → 切片执行 → 逐片审查 → 聚合 → 整体评估(evaluation.md)。
产物落盘 data/projects/<项目ID>/ 或 --project-dir 指定目录。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from pathlib import Path

from langchain_core.messages import HumanMessage

logger = logging.getLogger("cli.run")

_NODE_EVENTS = ("plan", "docs", "dispatch", "monitor", "replan", "aggregate", "evaluate")


async def run_chat(settings, message: str, role: str = "leader", project: str | None = None) -> dict:
    """跑一轮项目原型流水线,返回 {final_response, evaluation, project_dir}。"""
    from task_orchestrator.api.server import build_registry
    from task_orchestrator.common.llm import build_chat_model, build_tier_models
    from task_orchestrator.main_agent.graph import build_main_agent

    model = build_chat_model(settings)
    tier_models = build_tier_models(settings)
    registry = build_registry(model, role=role, dynamic_peers=(role == "leader"),
                              tier_models=tier_models, settings=settings)

    session_id = uuid.uuid4().hex[:8]
    project_dir = Path(project) if project else settings.data_dir / "projects" / session_id
    graph = build_main_agent(model, registry, role=role, models=tier_models,
                             project_dir=project_dir)

    print(f"\n[project] {project_dir}")
    print("[1/5] 理解意图 → 任务规划 → 落地文档 …")

    prev_plan: list[dict] = []
    final_response: str | None = None
    docs_printed = False
    eval_printed = False

    async for ev in graph.astream_events(
        {
            "messages": [HumanMessage(content=message)],
            "user_request": "",
            "task_plan": [],
            "final_response": "",
            "documents": {},
            "evaluation": "",
        },
        {"configurable": {"thread_id": session_id}},
        version="v2",
    ):
        if ev["event"] != "on_chain_end":
            continue
        name = ev.get("name", "")
        if name not in _NODE_EVENTS:
            continue
        output = ev.get("data", {}).get("output", {})
        if not isinstance(output, dict):
            continue

        if name == "docs" and output.get("documents") and not docs_printed:
            docs_printed = True
            print(f"[2/5] 落地文档已生成:\n"
                  f"    - 规划落地文档 -> {project_dir / 'plan.md'}\n"
                  f"    - 开发落地文档 -> {project_dir / 'dev.md'}")

        if name == "plan":
            plan = output.get("task_plan") or []
            if plan:
                print(f"[3/5] 任务计划({len(plan)} 个切片):")
                for t in plan:
                    deps = f" (依赖:{','.join(t['dependencies'])})" if t.get("dependencies") else ""
                    print(f"    - {t['task_id']}. [{t.get('agent_type')}] {t['description']}{deps}")
            else:
                print("[3/5] 未生成任务计划(将作为普通对话处理)")

        if name == "monitor":
            _print_task_deltas(prev_plan, output.get("task_plan") or [])
            prev_plan = copy.deepcopy(output.get("task_plan") or [])

        if name == "aggregate" and output.get("final_response"):
            final_response = output["final_response"]

        if name == "evaluate" and output.get("evaluation") and not eval_printed:
            eval_printed = True
            print(f"[5/5] 整体评估报告 -> {project_dir / 'evaluation.md'}")

    if final_response:
        print("\n" + "=" * 60)
        print(final_response)
    if eval_printed:
        print("=" * 60)
        print("(评估报告详见 evaluation.md;报告只列差距与不确定性,是否可用以实际运行为准)")
    print(f"产物目录: {project_dir}")
    return {
        "final_response": final_response or "",
        "project_dir": str(project_dir),
    }


def _print_task_deltas(prev: list[dict], curr: list[dict]) -> None:
    """控制台增量打印任务状态变化(完成/失败/等待审批/进度)。"""
    prev_map = {t["task_id"]: t for t in prev}
    for task in curr:
        tid = task["task_id"]
        before = prev_map.get(tid)
        before_status = before.get("status") if before else None
        status = task.get("status", "pending")
        desc = (task.get("original_description") or task.get("description") or "")[:60]
        if before is None:
            if status == "running":
                print(f"    >> [{tid}] {desc}")
            continue
        if before_status != status:
            if status == "completed":
                print(f"    [OK] [{tid}] 完成: {desc}")
            elif status == "failed":
                print(f"    [FAIL] [{tid}] 失败: {task.get('error', '')[:80]}")
            elif status == "waiting_approval":
                print(f"    [WAIT] [{tid}] 等待人工审批")
            elif status == "canceled":
                print(f"    [CANCEL] [{tid}] 已取消")
            elif status == "ready":
                print(f"    >> [{tid}] 开始执行(重试): {desc}")
        elif before_status == status == "running":
            bp = before.get("progress")
            cp = task.get("progress")
            if cp and cp != bp:
                print(f"    .. [{tid}] {cp[:80]}")


async def interactive_repl(settings, role: str = "leader", project: str | None = None) -> None:
    """交互式 REPL:每条输入跑一轮流水线。"""
    import sys

    print("◇ Task Orchestrator 项目原型流水线 — 交互模式")
    print("  输入项目构想(一句话或几行),回车执行;输入 quit 退出。\n")
    while True:
        try:
            line = input("构想> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in ("quit", "exit", "q"):
            break
        try:
            await run_chat(settings, stripped, role=role, project=project)
        except KeyboardInterrupt:
            print("\n(已中断本轮)")
        except Exception as exc:  # noqa: BLE001
            logger.exception("本轮执行失败")
            print(f"\n✘ 执行失败: {str(exc)[:300]}")
    sys.stdout.flush()