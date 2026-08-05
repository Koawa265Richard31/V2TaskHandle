"""A2A 1.0 适配器:把 A2A 远端 Agent 包装为统一 Adapter 接口。"""
from __future__ import annotations

import asyncio
import logging
import uuid

from task_orchestrator.adapters.a2a_client import RemoteAgentClient, RemoteAgentError
from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.a2a")

# A2A 协议状态 → 内部状态
_STATE_MAP = {
    "submitted": "running",
    "working": "running",
    "completed": "completed",
    "failed": "failed",
    "canceled": "failed",
    "rejected": "failed",
    "input-required": "running",
    "auth-required": "failed",
}


class A2AAdapter(BaseAdapter):
    """A2A 1.0 远端 Agent 适配器。submit 后台消费事件流,status/result 轮询远端。"""

    def __init__(self, url: str, api_key: str = "", timeout: float = 120.0):
        self.url = url
        self.client = RemoteAgentClient(url, api_key=api_key, timeout=timeout)
        self._connected = False
        self._card = None
        self._pending: dict[str, asyncio.Task] = {}  # external_id → 后台 send 任务
        self._results: dict[str, str] = {}
        self._errors: dict[str, str] = {}

    async def connect(self) -> None:
        """发现并验证远端 Agent。"""
        try:
            self._card = await self.client.connect()
            self._connected = True
        except RemoteAgentError as exc:
            logger.warning("A2A 适配器连接失败", extra={"url": self.url, "error": str(exc)})
            self._connected = False

    @property
    def agent_type(self) -> str:
        return "a2a"

    @property
    def is_available(self) -> bool:
        return self._connected

    @property
    def card(self):
        return self._card

    async def submit(self, task: dict) -> str:
        """后台提交任务到远端,返回内部 external_id。"""
        if not self._connected:
            raise RuntimeError(f"A2A Agent {self.url} 不可用")
        description = task.get("description", "")
        external_id = f"a2a_{uuid.uuid4().hex[:8]}"

        async def _send() -> None:
            result = await self.client.send(description)
            if result.task_id:
                # 后台流已消费完毕,用归一化结果
                self._results[external_id] = result.text
            else:
                # 无 task_id(纯流式),轮询可能拿不到终态,直接标记完成
                self._results[external_id] = result.text or "(完成)"

        run = asyncio.create_task(_send())
        self._pending[external_id] = run

        def _done(t: asyncio.Task) -> None:
            if t.cancelled():
                self._errors[external_id] = "任务已取消"
            elif t.exception() is not None:
                self._errors[external_id] = str(t.exception())

        run.add_done_callback(_done)
        return external_id

    async def status(self, external_id: str) -> str:
        run = self._pending.get(external_id)
        if run is None:
            return "failed"
        if run.done():
            return "completed" if external_id not in self._errors else "failed"
        return "running"

    async def result(self, external_id: str) -> str | None:
        if external_id in self._errors:
            return None
        if external_id in self._results:
            return self._results[external_id]
        return None

    async def cancel(self, external_id: str) -> bool:
        run = self._pending.get(external_id)
        if run and not run.done():
            run.cancel()
            return True
        return False

    async def close(self) -> None:
        await self.client.close()
