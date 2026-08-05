"""远端 REST 垂类 Agent 适配器:submit 提交异步任务,status/result 轮询远端。

与垂类 Agent(第三方开放注册)约定的 REST 约定:
- POST   {base_url}/tasks           提交任务 → {"task_id": "..."}
- GET    {base_url}/tasks/{id}      查询状态 → {"status": "completed|working|pending|failed"}
- GET    {base_url}/tasks/{id}/result  拉取结果 → {"content": "..."}
- DELETE {base_url}/tasks/{id}      取消(尽力而为)
认证:Authorization: Bearer <api_key>
"""
from __future__ import annotations

import logging

import httpx

from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.retrieval")

# 远端状态 → 内部统一状态
_STATE_MAP = {
    "completed": "completed",
    "failed": "failed",
    "error": "failed",
    "canceled": "failed",
    "rejected": "failed",
    "working": "running",
    "pending": "running",
    "running": "running",
    "submitted": "running",
    "queued": "running",
}


class RetrievalAdapter(BaseAdapter):
    """REST 异步任务适配器。submit 提交任务拿 task_id,status/result 轮询远端。"""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._httpx = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers=headers,
            transport=transport,
        )
        self._connected = False

    @property
    def agent_type(self) -> str:
        return "retrieval"

    @property
    def capabilities(self) -> list[str]:
        return ["retrieve"]

    @property
    def is_available(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """探测远端可用性与认证(200/404 视为可用,401/5xx/网络错误视为不可用)。"""
        try:
            resp = await self._httpx.get(f"{self.base_url}/health")
            self._connected = resp.status_code in (200, 404)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            logger.warning("检索 Agent 连接失败", extra={"url": self.base_url, "error": str(exc)})
            self._connected = False
        return self._connected

    async def submit(self, task: dict) -> str:
        """POST /tasks 提交异步任务,返回远端 task_id。"""
        if not self._connected:
            raise RuntimeError(f"远端检索 Agent {self.base_url} 不可用")
        description = task.get("description", "")
        params = task.get("params") or {}
        body = {"query": description, **params}
        resp = await self._httpx.post(f"{self.base_url}/tasks", json=body)
        resp.raise_for_status()
        data = resp.json()
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise RuntimeError(f"远端未返回 task_id:{data}")
        return str(task_id)

    async def status(self, external_id: str) -> str:
        """GET /tasks/{id} 查询状态,映射到 completed/running/failed。"""
        try:
            resp = await self._httpx.get(f"{self.base_url}/tasks/{external_id}")
            resp.raise_for_status()
            raw = resp.json().get("status", "working")
            return _STATE_MAP.get(str(raw).lower(), "running")
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            logger.warning("查询检索任务状态失败", extra={"task_id": external_id, "error": str(exc)})
            return "failed"

    async def result(self, external_id: str) -> str | None:
        """GET /tasks/{id}/result 拉取结果文本。"""
        try:
            resp = await self._httpx.get(f"{self.base_url}/tasks/{external_id}/result")
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content") or data.get("result") or data.get("text")
            return str(content).strip() if content else None
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            logger.warning("拉取检索任务结果失败", extra={"task_id": external_id, "error": str(exc)})
            return None

    async def cancel(self, external_id: str) -> bool:
        """DELETE /tasks/{id} 取消,尽力而为。"""
        try:
            resp = await self._httpx.delete(f"{self.base_url}/tasks/{external_id}")
            return resp.status_code < 400
        except httpx.TransportError:
            return False

    async def close(self) -> None:
        await self._httpx.aclose()
