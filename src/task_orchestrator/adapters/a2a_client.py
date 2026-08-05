"""A2A 1.0 客户端封装:发现、调用、流式消费、重试、错误归一化。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers.proto_helpers import (
    Role,
    TaskState,
    get_artifact_text,
    get_message_text,
    get_stream_response_text,
    new_text_message,
)
from a2a.types import (
    AgentCard,
    AgentInterface,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    SendMessageRequest,
    StreamResponse,
    Task,
)

logger = logging.getLogger("a2a.client")

_FINAL_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_INPUT_REQUIRED,
}

_STATE_NAME = {
    TaskState.TASK_STATE_SUBMITTED: "submitted",
    TaskState.TASK_STATE_WORKING: "working",
    TaskState.TASK_STATE_COMPLETED: "completed",
    TaskState.TASK_STATE_FAILED: "failed",
    TaskState.TASK_STATE_CANCELED: "canceled",
    TaskState.TASK_STATE_REJECTED: "rejected",
    TaskState.TASK_STATE_INPUT_REQUIRED: "input-required",
}


class RemoteAgentError(RuntimeError):
    """连接/协议层失败(已含重试)。"""


@dataclass
class RemoteCallResult:
    """一次远端委托的归一化结果。"""
    state: str
    text: str
    task_id: str | None = None
    context_id: str | None = None
    elapsed_ms: int = 0
    status_updates: list[str] = field(default_factory=list)

    @property
    def needs_input(self) -> bool:
        return self.state == TaskState.TASK_STATE_INPUT_REQUIRED.name


class RemoteAgentClient:
    """单个 A2A 1.0 远端 Agent 的客户端。"""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        headers = {"X-API-Key": api_key} if api_key else {}
        self._httpx = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0), headers=headers
        )
        self._client = None
        self.card: AgentCard | None = None

    async def connect(self) -> AgentCard:
        """拉取 AgentCard 并构建协议客户端。"""
        try:
            resolver = A2ACardResolver(httpx_client=self._httpx, base_url=self.base_url)
            self.card = await resolver.get_agent_card()
        except Exception as exc:
            raise RemoteAgentError(f"无法发现远端 Agent({self.base_url}):{exc}") from exc
        config = ClientConfig(streaming=True, httpx_client=self._httpx)
        self._client = await create_client(agent=self.card, client_config=config)
        logger.info("已连接远端 Agent", extra={"name": self.card.name, "url": self.base_url})
        return self.card

    async def send(
        self,
        text: str,
        context_id: str | None = None,
        task_id: str | None = None,
        max_attempts: int = 3,
    ) -> RemoteCallResult:
        """发送消息并消费完整事件流,返回归一化结果。"""
        if self._client is None:
            await self.connect()

        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                started = time.monotonic()
                result = await self._send_once(text, context_id, task_id)
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
                return result
            except _RetryableTransport as exc:
                last_error = exc.cause
                if exc.received_any or not exc.retryable:
                    break
            if attempt + 1 >= max_attempts:
                break
            await asyncio.sleep(0.5 * (2 ** attempt))

        name = self.card.name if self.card else self.base_url
        raise RemoteAgentError(f"远端 Agent「{name}」调用失败:{last_error}")

    async def query(self, task_id: str) -> RemoteCallResult:
        """查询远端任务当前状态(异步轮询用)。"""
        if self._client is None:
            await self.connect()
        task = await self._client.get_task(GetTaskRequest(id=task_id))
        state = _STATE_NAME.get(task.status.state, "working")
        texts = [get_artifact_text(a) for a in (task.artifacts or [])]
        return RemoteCallResult(
            state=state,
            text="\n".join(t for t in texts if t),
            task_id=task.id,
            context_id=task.context_id,
        )

    async def cancel_task(self, task_id: str) -> bool:
        """取消远端任务,返回是否成功。"""
        if self._client is None:
            await self.connect()
        try:
            await self._client.cancel_task(CancelTaskRequest(id=task_id))
            return True
        except Exception as exc:
            logger.warning("取消远端任务失败", extra={"task_id": task_id, "error": str(exc)})
            return False

    async def _send_once(
        self, text: str, context_id: str | None, task_id: str | None
    ) -> RemoteCallResult:
        message = new_text_message(text, role=Role.ROLE_USER)
        if context_id:
            message.context_id = context_id
        if task_id:
            message.task_id = task_id

        request = SendMessageRequest(message=message)
        status_updates: list[str] = []
        final_task: Task | None = None
        final_state: str = ""
        received_any = False
        artifact_texts: list[str] = []
        last_status_message: str = ""

        try:
            async for event in self._client.send_message(request):
                received_any = True
                sr: StreamResponse = event

                if sr.HasField("task"):
                    final_task = sr.task
                    task_state = sr.task.status.state
                    if task_state in _FINAL_STATES:
                        final_state = _STATE_NAME.get(task_state, str(task_state))
                        break

                if sr.HasField("status_update"):
                    update = sr.status_update
                    status_state = update.status.state
                    if update.status.message:
                        msg = get_message_text(update.status.message)
                        if msg:
                            last_status_message = msg
                            status_updates.append(msg)
                    if status_state in _FINAL_STATES:
                        final_state = _STATE_NAME.get(status_state, str(status_state))

                if sr.HasField("artifact_update"):
                    atf = sr.artifact_update
                    if atf.artifact:
                        for p in atf.artifact.parts:
                            if p.text:
                                artifact_texts.append(p.text)

        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            raise _RetryableTransport(exc, received_any) from exc

        if not final_state:
            final_state = "completed"

        text_out = "\n".join(artifact_texts) or last_status_message or (
            status_updates[-1] if status_updates else ""
        )

        return RemoteCallResult(
            state=final_state,
            text=text_out.strip(),
            task_id=final_task.id if final_task else None,
            context_id=final_task.context_id if final_task else context_id,
            status_updates=status_updates,
        )

    async def close(self) -> None:
        await self._httpx.aclose()


class _RetryableTransport(Exception):
    def __init__(self, cause: Exception, received_any: bool):
        super().__init__(str(cause))
        self.cause = cause
        self.received_any = received_any
        self.captured_status: int | None = None

    @property
    def retryable(self) -> bool:
        status = getattr(self.cause, "status_code", None)
        if status is None:
            resp = getattr(self.cause, "response", None)
            status = getattr(resp, "status_code", None)
        return status is None or int(status) >= 500
