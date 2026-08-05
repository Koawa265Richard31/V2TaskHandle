"""本地工具适配器:包装进程内 Local Agent,后台任务执行 + 轮询。"""
from __future__ import annotations

import asyncio
import logging
import uuid

from langchain_core.language_models.chat_models import BaseChatModel

from task_orchestrator.adapters.base import BaseAdapter
from task_orchestrator.local_agent.tools import build_local_agent

logger = logging.getLogger("adapters.local")


class LocalAdapter(BaseAdapter):
    """本地工具 Agent 适配器。submit 时在后台跑 ReAct 图,status/result 轮询结果。"""

    def __init__(
        self,
        enabled_tools: list[str] | None = None,
        model: BaseChatModel | None = None,
    ):
        self._enabled = set(enabled_tools if enabled_tools is not None else ["shell", "file", "web"])
        self._model = model
        self._runs: dict[str, asyncio.Task] = {}
        self._results: dict[str, str | None] = {}
        self._errors: dict[str, str | None] = {}

    @property
    def agent_type(self) -> str:
        return "local"

    @property
    def capabilities(self) -> list[str]:
        caps = []
        if "file" in self._enabled or "shell" in self._enabled:
            caps.append("code")
        if "file" in self._enabled:
            caps.append("doc")
        return caps

    @property
    def is_available(self) -> bool:
        return len(self._enabled) > 0

    @property
    def enabled_tools(self) -> list[str]:
        return sorted(self._enabled)

    def set_model(self, model: BaseChatModel) -> None:
        """注入本地 Agent 用的 LLM(默认用全局 factory 构造)。"""
        self._model = model

    def _ensure_graph(self):
        from task_orchestrator.common.llm import build_chat_model
        if self._model is None:
            self._model = build_chat_model()
        return build_local_agent(self._model, enabled_tools=sorted(self._enabled))

    async def submit(self, task: dict) -> str:
        task_id = f"local_{uuid.uuid4().hex[:8]}"
        graph = self._ensure_graph()
        description = task.get("description", "")

        async def _run() -> str:
            try:
                result = await graph.ainvoke({"messages": [("human", description)]})
                last = result["messages"][-1]
                content = last.content
                if isinstance(content, list):
                    content = "".join(
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    )
                return str(content).strip() or "(无输出)"
            except Exception as exc:
                logger.error("本地执行失败", extra={"error": str(exc)})
                raise

        task_obj = asyncio.create_task(_run())
        self._runs[task_id] = task_obj

        def _done(t: asyncio.Task) -> None:
            if t.cancelled():
                self._errors[task_id] = "任务已取消"
            elif t.exception() is not None:
                self._errors[task_id] = str(t.exception())
            else:
                self._results[task_id] = t.result()

        task_obj.add_done_callback(_done)
        return task_id

    async def status(self, external_id: str) -> str:
        task = self._runs.get(external_id)
        if task is None:
            return "failed"
        if task.done():
            return "completed" if not task.cancelled() and task.exception() is None else "failed"
        return "running"

    async def result(self, external_id: str) -> str | None:
        if external_id in self._results:
            return self._results[external_id]
        if external_id in self._errors:
            return None
        return None

    async def cancel(self, external_id: str) -> bool:
        task = self._runs.get(external_id)
        if task and not task.done():
            task.cancel()
            return True
        return False
