"""Codex SDK 适配器 + Mock 变体。"""
from __future__ import annotations

import logging

from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.codex")


class MockCodexAdapter(BaseAdapter):
    """测试用 Codex 适配器:返回预设结果,无需真实 Codex 环境。"""

    def __init__(self, mock_results: dict[str, str] | None = None):
        self._results = mock_results or {
            "default": "Mock Codex 执行完成:代码已修改。",
        }

    @property
    def agent_type(self) -> str:
        return "codex"

    @property
    def capabilities(self) -> list[str]:
        return ["code"]

    @property
    def is_available(self) -> bool:
        return True

    async def submit(self, task: dict) -> str:
        task_id = f"mock_codex_{hash(task.get('description', ''))}"
        return task_id

    async def status(self, external_id: str) -> str:
        return "completed"

    async def result(self, external_id: str) -> str | None:
        return self._results.get(external_id, self._results["default"])

    async def cancel(self, external_id: str) -> bool:
        return True


class CodexAdapter(BaseAdapter):
    """Codex SDK 适配器:封装 openai-codex Python SDK。

    pip install openai-codex 后可启用。默认使用 MockCodexAdapter 作为测试/降级方案。
    """

    def __init__(self, sandbox: str = "workspace_write", model: str = "gpt-5.4"):
        self.sandbox = sandbox
        self.model = model
        self._available = False
        self._mock = MockCodexAdapter()
        try:
            import openai_codex as _  # noqa: F401
            self._available = True
        except ImportError:
            logger.info("openai-codex 未安装,使用 MockCodexAdapter")

    @property
    def agent_type(self) -> str:
        return "codex"

    @property
    def capabilities(self) -> list[str]:
        return ["code"]

    @property
    def is_available(self) -> bool:
        return self._available

    async def submit(self, task: dict) -> str:
        if not self._available:
            return await self._mock.submit(task)

        description = task.get("description", "")
        try:
            from openai_codex import AsyncCodex, Sandbox
            async with AsyncCodex() as codex:
                thread = await codex.thread_start(
                    sandbox=getattr(Sandbox, self.sandbox, Sandbox.workspace_write),
                    model=self.model,
                )
                result = await thread.run(description)
                return thread.id
        except Exception as exc:
            logger.error("Codex 调用失败", extra={"error": str(exc)})
            raise

    async def status(self, external_id: str) -> str:
        return "completed"

    async def result(self, external_id: str) -> str | None:
        if not self._available:
            return await self._mock.result(external_id)
        return f"Codex 执行完成 (thread: {external_id})"

    async def cancel(self, external_id: str) -> bool:
        return False
