"""McpAgentAdapter 单元测试:验证 JSON-RPC connect/submit/status/result。"""
import asyncio

import httpx
import pytest

from task_orchestrator.adapters.mcp_adapter import McpAgentAdapter


class MockTransport(httpx.AsyncBaseTransport):
    """可控的 httpx transport:按 URL/body 返回预设响应,模拟 MCP Server 行为。"""

    def __init__(self, responses: list[dict] | None = None, raise_error: Exception | None = None):
        self.responses = responses or []
        self.raise_error = raise_error
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content) if request.content else {}
        self.requests.append(body)
        method = body.get("method", "")

        if self.raise_error:
            raise self.raise_error

        # 从后往前匹配:后面的 preset 优先,允许 exta 覆盖默认
        for preset in reversed(self.responses):
            if preset.get("method") == method:
                status = preset.get("status", 200)
                resp_body = preset.get("body", {})
                return httpx.Response(status, json=resp_body, request=request)

        # 默认:返回空成功
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": {}, "id": body.get("id")}, request=request)


def _make_transport(extra_responses: list[dict] | None = None) -> MockTransport:
    """构造标准 MCP mock:initialize + tools/list 返回 3 个工具。"""
    responses = [
        {
            "method": "initialize",
            "status": 200,
            "body": {
                "jsonrpc": "2.0",
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "test-server", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                },
                "id": 1,
            },
        },
        {
            "method": "tools/list",
            "status": 200,
            "body": {
                "jsonrpc": "2.0",
                "result": {
                    "tools": [
                        {"name": "weather_query", "description": "查询天气"},
                        {"name": "ticket_query", "description": "查询工单"},
                        {"name": "sales_query", "description": "查询销售数据"},
                    ]
                },
                "id": 2,
            },
        },
        {
            "method": "tools/call",
            "status": 200,
            "body": {
                "jsonrpc": "2.0",
                "result": {
                    "content": [{"type": "text", "text": "今天北京晴, 25°C"}],
                },
                "id": 3,
            },
        },
    ]
    if extra_responses:
        responses.extend(extra_responses)
    return MockTransport(responses)


# ── 测试 connect ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_success():
    """connect 应成功发现工具,is_available=True。"""
    transport = _make_transport()
    adapter = McpAgentAdapter("http://test/mcp", transport=transport)
    ok = await adapter.connect()
    assert ok is True
    assert adapter.is_available
    assert adapter.agent_type == "mcp"
    assert "weather_query" in adapter.capabilities
    assert "ticket_query" in adapter.capabilities
    assert "sales_query" in adapter.capabilities
    assert len(adapter.tools) == 3
    await adapter.close()


@pytest.mark.asyncio
async def test_connect_failure_network_error():
    """connect 遇到网络错误时返回 False。"""
    transport = MockTransport(raise_error=httpx.ConnectError("connection refused"))
    adapter = McpAgentAdapter("http://bad/mcp", transport=transport)
    ok = await adapter.connect()
    assert ok is False
    assert not adapter.is_available
    await adapter.close()


@pytest.mark.asyncio
async def test_connect_failure_rpc_error():
    """connect 遇到 JSON-RPC error 时返回 False。"""
    transport = _make_transport([
        {
            "method": "initialize",
            "status": 200,
            "body": {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": "Method not found"},
                "id": 1,
            },
        },
    ])
    adapter = McpAgentAdapter("http://bad/mcp", transport=transport)
    ok = await adapter.connect()
    assert ok is False
    await adapter.close()


# ── 测试 submit ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_with_tool_name():
    """指定 tool_name 的 submit 应调 tools/call 并返回结果。"""
    transport = _make_transport()
    adapter = McpAgentAdapter("http://test/mcp", transport=transport)
    await adapter.connect()

    task_id = await adapter.submit({
        "description": "查天气",
        "tool_name": "weather_query",
        "params": {"city": "北京"},
    })
    assert task_id.startswith("mcp_")

    status = await adapter.status(task_id)
    assert status == "completed"

    result = await adapter.result(task_id)
    assert result == "今天北京晴, 25°C"

    await adapter.close()


@pytest.mark.asyncio
async def test_submit_matches_by_description():
    """无显式 tool_name 时,从 description 首词匹配。"""
    transport = _make_transport()
    adapter = McpAgentAdapter("http://test/mcp", transport=transport)
    await adapter.connect()

    task_id = await adapter.submit({"description": "weather_query 查天气"})
    assert task_id.startswith("mcp_")
    assert await adapter.status(task_id) == "completed"

    await adapter.close()


@pytest.mark.asyncio
async def test_submit_when_not_connected():
    """未 connect 时 submit 应抛 RuntimeError。"""
    adapter = McpAgentAdapter("http://test/mcp")
    with pytest.raises(RuntimeError, match="不可用"):
        await adapter.submit({"description": "test"})
    await adapter.close()


@pytest.mark.asyncio
async def test_submit_with_rpc_error():
    """tools/call 失败时 status 返回 failed。"""
    transport = _make_transport([
        {
            "method": "tools/call",
            "status": 200,
            "body": {
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": "Invalid params"},
                "id": 3,
            },
        },
    ])
    adapter = McpAgentAdapter("http://test/mcp", transport=transport)
    await adapter.connect()

    task_id = await adapter.submit({"tool_name": "weather_query"})
    assert await adapter.status(task_id) == "failed"
    result = await adapter.result(task_id)
    assert result is None

    await adapter.close()


# ── 测试 cancel ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_returns_false():
    """MCP 同步调用无法取消。"""
    adapter = McpAgentAdapter("http://test/mcp")
    assert await adapter.cancel("mcp_xxx") is False
    await adapter.close()
