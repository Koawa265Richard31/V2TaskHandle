"""LlmAdapter:便宜档位模型直接执行文本/文档/草稿类切片(implementer 角色)。

适合高频、量大、不需要工具的切片:文档段落、代码草稿、文案、数据整理等。
实现方式:把 task.description(+依赖切片上下文)交给分档模型生成文本,立即返回。
"""
from __future__ import annotations

import logging
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.llm")

IMPLEMENTER_PROMPT = """你是一名一线实现者。按下面的任务要求直接产出结果,不要反问,不要解释过程。

规则:
1. 只输出任务要求的交付物本身(文本/代码/文档片段),不加"以下是…"之类的前缀
2. 要求是代码时,直接输出代码块
3. 要求是文档/文案时,直接输出 markdown 内容
4. 若给了上游上下文(依赖切片的产物),先理解再产出,可引用其中的事实
5. 结果要完整、可独立提交审查
"""


class LlmAdapter(BaseAdapter):
    """implementer 适配器:模型生成式执行切片,结果内存缓存,立即完成。"""

    def __init__(self, model: BaseChatModel | None = None, timeout: float = 120.0):
        self._model = model
        self._timeout = timeout
        self._results: dict[str, str] = {}

    @property
    def agent_type(self) -> str:
        return "implementer"

    @property
    def name(self) -> str:
        return "implementer"

    @property
    def capabilities(self) -> list[str]:
        return ["write", "doc", "draft"]

    @property
    def is_available(self) -> bool:
        return self._model is not None

    async def submit(self, task: dict) -> str:
        description = task.get("description", "")
        context = task.get("context") or ""
        user_part = f"任务要求:\n{description}"
        if context:
            user_part += f"\n\n可用的上游上下文:\n{context}"
        response = await self._model.ainvoke([
            SystemMessage(content=IMPLEMENTER_PROMPT),
            HumanMessage(content=user_part),
        ])
        text = str(response.content).strip()
        ext_id = f"impl-{uuid.uuid4().hex[:12]}"
        self._results[ext_id] = text
        logger.info(
            "implementer 切片完成",
            extra={"task_id": task.get("task_id"), "chars": len(text)},
        )
        return ext_id

    async def status(self, external_id: str) -> str:
        return "completed" if external_id in self._results else "running"

    async def result(self, external_id: str) -> str | None:
        return self._results.get(external_id)

    async def cancel(self, external_id: str) -> bool:
        self._results.pop(external_id, None)
        return True