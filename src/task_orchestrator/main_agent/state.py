"""Main Agent 状态与子任务数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


@dataclass
class SubTask:
    """计划中的一个子任务。"""
    task_id: str
    description: str
    agent_type: str          # "a2a" | "codex" | "local" | "retrieval" | "codex_cli"
    agent_target: str        # A2A: url, Codex: sandbox, Local: tool_name
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | ready | running | waiting_approval | completed | failed
    result: str | None = None
    error: str | None = None
    # 审批模式(需监控任务): ask(强提醒人工介入) / auto(自动执行) / full(完全绕过)
    approval_mode: str = "auto"
    # 最新进度文本(需监控任务,长任务边跑边更新)
    progress: str | None = None
    # 是否需监控任务(capability=code/doc → True,侧栏单独分栏)
    requires_monitor: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "agent_type": self.agent_type,
            "agent_target": self.agent_target,
            "dependencies": self.dependencies,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "approval_mode": self.approval_mode,
            "progress": self.progress,
            "requires_monitor": self.requires_monitor,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SubTask":
        return cls(
            task_id=str(d["task_id"]),
            description=d["description"],
            agent_type=d.get("agent_type", "local"),
            agent_target=d.get("agent_target", ""),
            dependencies=d.get("dependencies", []),
            status=d.get("status", "pending"),
            result=d.get("result"),
            error=d.get("error"),
            approval_mode=d.get("approval_mode", "auto"),
            progress=d.get("progress"),
            requires_monitor=d.get("requires_monitor", False),
        )


from typing import TypedDict


class MainAgentState(TypedDict):
    """Main Agent 的 GraphState。"""
    messages: Annotated[list[BaseMessage], add_messages]
    user_request: str
    task_plan: list[dict[str, Any]]
    final_response: str
    # 项目原型流水线状态:落地文档与整体评估报告(均为 md 文本)
    documents: dict[str, str]          # {"plan": ..., "dev": ...}
    evaluation: str                    # 整体评估报告文本
