"""注册批准集成测试:起真实注册中心 uvicorn,走真实 HTTP 验证注册/申请/批准/发现闭环。"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
import uvicorn

from task_orchestrator.common.db import Database
from task_orchestrator.registry_client import RegistryClient
from task_orchestrator.registry_center.app import build_app

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def registry_server(tmp_path):
    """启动真实注册中心 uvicorn。"""
    db = Database(tmp_path / "registry.db")
    app = build_app(db)
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("注册中心启动超时")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
    db.close()


@pytest.mark.asyncio
async def test_full_approval_flow(registry_server):
    """组长注册 → 组员注册+申请 → 组长批准 → 组长发现已批准组员。"""
    client = RegistryClient(registry_server)

    # 组长登记
    leader_id = await client.register("组长PT", "http://h:8000", "leader")
    # 组员登记
    member_id = await client.register("组员PT", "http://m:8101", "member")

    # 组员申请加入组长团队
    request_id = await client.join_request(member_id, "组员PT", "http://m:8101", leader_id)

    # 组长看到 pending 申请
    reqs = await client.list_requests(leader_id, status="pending")
    assert len(reqs) == 1
    assert reqs[0]["peer_name"] == "组员PT"

    # 组长批准
    status = await client.approve(request_id, approve=True)
    assert status == "approved"

    # 组长拉取已批准组员
    approved = await client.approved_peers(leader_id)
    assert len(approved) == 1
    assert approved[0]["name"] == "组员PT"
    assert approved[0]["url"] == "http://m:8101"

    await client.close()


@pytest.mark.asyncio
async def test_rejected_not_discovered(registry_server):
    client = RegistryClient(registry_server)
    leader_id = await client.register("组长", "http://h:8000", "leader")
    member_id = await client.register("组员", "http://m:8101", "member")
    request_id = await client.join_request(member_id, "组员", "http://m:8101", leader_id)

    await client.approve(request_id, approve=False)
    assert await client.approved_peers(leader_id) == []
    await client.close()
