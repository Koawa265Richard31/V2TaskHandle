"""MCP 协议适配器:通过 JSON-RPC 2.0 over HTTP 连接 MCP Server,包装为统一 Adapter 接口。

与 ragent (Java Spring Boot MCP Server, /mcp 端点) 等 MCP 兼容服务对接。

JSON-RPC 协议约定:
- 所有请求 POST {base_url} (通常是 http://host:port/mcp)
- 请求体: {"jsonrpc": "2.0", "method": "...", "params": {...}, "id": N}
- 响应体: {"jsonrpc": "2.0", "result": {...}, "id": N}
- 错误: {"jsonrpc": "2.0", "error": {"code": ..., "message": "..."}, "id": N}
"""
from __future__ import annotations

import logging
import uuid

import httpx

from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.mcp")

MCP_PROTOCOL_VERSION = "2024-11-05"

# 远端状态 → 内部统一状态
_STATE_MAP = {
    "completed": "completed",
    "failed": "failed",
    "error": "failed",
}


class McpAgentAdapter(BaseAdapter):
    """MCP 协议适配器:通过 JSON-RPC 连接 MCP Server,同步调用工具。"""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        headers.setdefault("Content-Type", "application/json")
        self._httpx = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers=headers,
            transport=transport,
        )
        self._connected = False
        self._tools: dict[str, dict] = {}  # tool_name → tool_definition
        self._results: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        """发送 JSON-RPC 2.0 请求,返回 result 或抛异常。"""
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id(),
        }
        logger.debug("MCP JSON-RPC => %s", method, extra={"params": str(params)[:200]})
        resp = await self._httpx.post(self.base_url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            err = data["error"]
            msg = err.get("message", "MCP RPC error")
            raise RuntimeError(f"MCP {method} 失败: {msg}")
        return data.get("result", {}) or {}

    # ── BaseAdapter ──────────────────────────────────────────

    @property
    def agent_type(self) -> str:
        return "mcp"

    @property
    def capabilities(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def tools(self) -> dict[str, dict]:
        """已发现的 MCP 工具: {name: {description, inputSchema, ...}}。"""
        return dict(self._tools)

    @property
    def is_available(self) -> bool:
        return self._connected and bool(self._tools)

    async def connect(self) -> bool:
        """发送 initialize + tools/list,发现可用工具。"""
        try:
            # 1. initialize
            await self._rpc("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "task-orchestrator", "version": "0.1.0"},
                "capabilities": {},
            })
            # 2. tools/list
            result = await self._rpc("tools/list")
            tools_raw = result.get("tools", [])
            self._tools = {}
            for tool in tools_raw:
                name = tool.get("name")
                if name:
                    self._tools[name] = tool
            self._connected = True
            logger.info(
                "MCP 适配器连接成功",
                extra={"url": self.base_url, "tools": list(self._tools.keys())},
            )
        except Exception as exc:
            logger.warning(
                "MCP 适配器连接失败",
                extra={"url": self.base_url, "error": str(exc)},
            )
            self._connected = False
        return self._connected

    async def submit(self, task: dict) -> str:
        """调 tools/call 同步执行工具,返回 internal task_id。"""
        if not self._connected:
            raise RuntimeError(f"MCP Agent {self.base_url} 不可用")

        tool_name = (
            task.get("tool_name")
            or task.get("agent_type")
            or task.get("description", "")
        )
        tool_args = task.get("params") or task.get("tool_args") or {}

        # 没有显式指定 tool_name 时,尝试从 description 首词匹配
        if tool_name not in self._tools:
            first_word = str(task.get("description", "")).split()[0].lower().rstrip(":")
            candidates = [n for n in self._tools if first_word in n.lower()]
            if len(candidates) == 1:
                tool_name = candidates[0]
            elif candidates:
                logger.warning(
                    "多个 MCP 工具候选,取第一个",
                    extra={"candidates": candidates, "description": task.get("description")},
                )
                tool_name = candidates[0]

        external_id = f"mcp_{uuid.uuid4().hex[:8]}"
        try:
            resp = await self._rpc("tools/call", {
                "name": tool_name,
                "arguments": tool_args,
            })
            # 提取文本内容
            content = resp.get("content", [])
            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                text = "\n".join(text_parts)
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)

            self._results[external_id] = text or "(工具返回空结果)"
            logger.info("MCP 工具调用完成", extra={"tool": tool_name, "task_id": external_id})
        except Exception as exc:
            self._errors[external_id] = str(exc)
            logger.warning("MCP 工具调用失败", extra={"tool": tool_name, "error": str(exc)})

        return external_id

    async def status(self, external_id: str) -> str:
        if external_id in self._errors:
            return "failed"
        if external_id in self._results:
            return "completed"
        return "running"

    async def result(self, external_id: str) -> str | None:
        return self._results.get(external_id)

    async def cancel(self, external_id: str) -> bool:
        # MCP 同步调用无法取消
        return False

    async def close(self) -> None:
        await self._httpx.aclose()
