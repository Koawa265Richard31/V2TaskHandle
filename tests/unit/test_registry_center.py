"""注册中心逻辑单元测试:用真实 Database(tmp) 验证 register/join/approve/approved。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from fastapi.testclient import TestClient

from task_orchestrator.common.db import Database
from task_orchestrator.registry_center.app import build_app


@pytest.fixture
def client(tmp_path):
    db = Database(tmp_path / "registry.db")
    app = build_app(db)
    yield TestClient(app)
    db.close()


def test_register_and_peers(client):
    r = client.post("/api/register", json={"name": "组长PT", "url": "http://h:8000", "role": "leader"})
    assert r.status_code == 200
    leader_id = r.json()["peer_id"]

    r = client.post("/api/register", json={"name": "组员PT", "url": "http://m:8101", "role": "member"})
    member_id = r.json()["peer_id"]

    peers = client.get("/api/peers").json()
    assert len(peers) == 2
    members = client.get("/api/peers", params={"role": "member"}).json()
    assert len(members) == 1
    assert members[0]["id"] == member_id


def test_join_approve_flow(client):
    # 注册组长+组员
    leader_id = client.post("/api/register", json={"name": "组长", "url": "http://h:8000", "role": "leader"}).json()["peer_id"]
    member_id = client.post("/api/register", json={"name": "组员", "url": "http://m:8101", "role": "member"}).json()["peer_id"]

    # 组员发加入申请
    r = client.post("/api/join-request", json={
        "peer_id": member_id, "peer_name": "组员", "peer_url": "http://m:8101", "leader_id": leader_id,
    })
    assert r.status_code == 200
    request_id = r.json()["request_id"]

    # 组长看到 pending 请求
    reqs = client.get("/api/requests", params={"leader_id": leader_id}).json()
    assert len(reqs) == 1
    assert reqs[0]["status"] == "pending"

    # 批准前 approved 为空
    assert client.get("/api/approved", params={"leader_id": leader_id}).json() == []

    # 组长批准
    r = client.post("/api/approve", json={"request_id": request_id, "approve": True})
    assert r.json()["status"] == "approved"

    # 批准后 approved 可见
    approved = client.get("/api/approved", params={"leader_id": leader_id}).json()
    assert len(approved) == 1
    assert approved[0]["name"] == "组员"
    assert approved[0]["url"] == "http://m:8101"


def test_join_reject(client):
    leader_id = client.post("/api/register", json={"name": "组长", "url": "http://h:8000", "role": "leader"}).json()["peer_id"]
    member_id = client.post("/api/register", json={"name": "组员", "url": "http://m:8101"}).json()["peer_id"]
    request_id = client.post("/api/join-request", json={
        "peer_id": member_id, "peer_name": "组员", "peer_url": "http://m:8101", "leader_id": leader_id,
    }).json()["request_id"]

    client.post("/api/approve", json={"request_id": request_id, "approve": False})
    assert client.get("/api/approved", params={"leader_id": leader_id}).json() == []


def test_approve_missing_request(client):
    r = client.post("/api/approve", json={"request_id": 999, "approve": True})
    assert r.status_code == 404
