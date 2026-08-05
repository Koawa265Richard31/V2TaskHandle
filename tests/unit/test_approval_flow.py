"""审批闭环测试:waiting_approval 任务的前端批准/改策略重跑端点。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from fastapi.testclient import TestClient

from task_orchestrator.api import server


class FakeCodexCliAdapter:
    """最小 codex_cli mock:submit 记录调用,立即 completed。"""

    agent_type = "codex_cli"

    def __init__(self):
        self.submitted: list[dict] = []
        self._waiting_approval: dict[str, bool] = {}

    @property
    def is_available(self) -> bool:
        return True

    async def submit(self, task: dict) -> str:
        self.submitted.append(dict(task))
        return f"fake_ext_{len(self.submitted)}"

    async def status(self, external_id: str) -> str:
        return "completed"

    async def result(self, external_id: str) -> str | None:
        return "完成"

    async def cancel(self, external_id: str) -> bool:
        return True


@pytest.fixture
def client(monkeypatch):
    # 注入假 adapter:build_registry 返回含 FakeCodexCliAdapter 的 registry
    fake = FakeCodexCliAdapter()

    def _fake_build_registry(model=None, role="leader", dynamic_peers=False):
        from task_orchestrator.registry import AgentRegistry
        r = AgentRegistry()
        r.register(fake, "codex_cli")
        return r

    monkeypatch.setattr(server, "build_registry", _fake_build_registry)
    # 注入一个 waiting_approval 的会话
    server._sessions["sess_test"] = {
        "task_plan": [{
            "task_id": "7", "description": "codex 任务", "agent_type": "codex_cli",
            "status": "waiting_approval", "approval_mode": "ask", "error": "等待人工审批",
        }],
        "role": "leader",
        "ts": 0.0,
    }
    return TestClient(server.app), fake


def test_retry_with_approval_changes_mode(client):
    test_client, fake = client
    r = test_client.post("/api/tasks/7/retry_with_approval", json={
        "session_id": "sess_test", "task_id": "7", "approval_mode": "full",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["approval_mode"] == "full"
    # 会话里任务状态变 running
    task = server._sessions["sess_test"]["task_plan"][0]
    assert task["status"] == "running"
    # 假 adapter 收到重新 submit,且带新 approval_mode
    assert len(fake.submitted) == 1
    assert fake.submitted[0]["approval_mode"] == "full"


def test_approve_runs_task(client):
    test_client, fake = client
    r = test_client.post("/api/tasks/7/approve", json={
        "session_id": "sess_test", "task_id": "7",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    task = server._sessions["sess_test"]["task_plan"][0]
    assert task["status"] == "running"
    assert len(fake.submitted) == 1


def test_approve_wrong_status_rejected(client):
    test_client, _ = client
    # 改状态为 completed,非 waiting_approval
    server._sessions["sess_test"]["task_plan"][0]["status"] = "completed"
    r = test_client.post("/api/tasks/7/approve", json={
        "session_id": "sess_test", "task_id": "7",
    })
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_approve_missing_session(client):
    test_client, _ = client
    r = test_client.post("/api/tasks/9/approve", json={
        "session_id": "no_such", "task_id": "7",
    })
    assert r.status_code == 404
