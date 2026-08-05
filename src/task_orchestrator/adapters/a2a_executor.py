"""通用 A2A 1.0 AgentExecutor:把 LangGraph 图适配为 A2A 服务端执行器。"""
from __future__ import annotations

import logging

from a2a.helpers.proto_helpers import (
    Role,
    TaskState,
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_status_update_event,
    new_text_artifact,
    new_text_artifact_update_event,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Task
from a2a.utils.errors import UnsupportedOperationError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

logger = logging.getLogger("a2a.executor")


class LangGraphAgentExecutor(AgentExecutor):
    """LLM 型远端的通用执行器:A2A 1.0 协议适配器 + LangGraph 图。"""

    def __init__(self, graph, agent_name: str, working_hint: str = "正在处理…"):
        self.graph = graph
        self.agent_name = agent_name
        self.working_hint = working_hint

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = get_message_text(context.message) if context.message else ""
        task = context.current_task

        is_continuation = task is not None
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        logger.info("收到委托", extra={"agent": self.agent_name, "continuation": is_continuation})

        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message(self.working_hint),
        )

        try:
            messages = self._history_messages(task) if is_continuation else []
            messages.append(HumanMessage(content=query))
            result = await self.graph.ainvoke({"messages": messages})
            final_text = self._final_text(result)
        except Exception:
            logger.exception("内部 agent 执行失败", extra={"agent": self.agent_name})
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message("内部处理出错,请稍后重试。"),
            )
            return

        artifact = new_text_artifact("result", final_text)
        await updater.add_artifact(artifact.parts, name="result")
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("委托完成"),
        )
        logger.info("委托完成", extra={"agent": self.agent_name})

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()

    @staticmethod
    def _history_messages(task: Task) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for msg in (task.history or [])[:-1]:
            text = get_message_text(msg)
            if not text:
                continue
            if msg.role == Role.ROLE_USER:
                messages.append(HumanMessage(content=text))
            else:
                messages.append(AIMessage(content=text))
        return messages

    @staticmethod
    def _final_text(result: dict) -> str:
        last = result["messages"][-1]
        content = last.content
        if isinstance(content, list):
            content = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        return str(content).strip() or "(无输出)"
