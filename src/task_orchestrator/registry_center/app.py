"""中央注册中心:PT 实例登记、发现、加入申请、组长批准。

跨环境(云端)协作的共享锚点。所有 PT 启动时向这里登记自身(name/url/role),
组员向组长发加入申请,组长(人类)批准后该组员才对组长可见可下发。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from task_orchestrator.common.db import Database

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS peers ("
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  name TEXT NOT NULL,"
    "  url TEXT NOT NULL,"
    "  role TEXT NOT NULL DEFAULT 'member',"
    "  description TEXT DEFAULT '',"
    "  created_at INTEGER NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS requests ("
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  peer_id INTEGER NOT NULL,"
    "  peer_name TEXT NOT NULL,"
    "  peer_url TEXT NOT NULL,"
    "  leader_id INTEGER NOT NULL,"
    "  status TEXT NOT NULL DEFAULT 'pending',"  # pending | approved | rejected
    "  created_at INTEGER NOT NULL,"
    "  decided_at INTEGER"
    ")",
]


class PeerIn(BaseModel):
    name: str
    url: str
    role: str = "member"
    description: str = ""


class JoinRequestIn(BaseModel):
    peer_id: int
    peer_name: str
    peer_url: str
    leader_id: int


class ApproveIn(BaseModel):
    request_id: int
    approve: bool = True  # True=批准, False=拒绝


def build_app(db: Database) -> FastAPI:
    db.migrate("registry_v1", _SCHEMA)
    app = FastAPI(title="PT Registry Center")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _peer_row(row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "role": row["role"],
            "description": row.get("description", ""),
        }

    @app.post("/api/register")
    async def register(p: PeerIn):
        """PT 实例登记,返回 peer_id。"""
        rid = db.insert(
            "INSERT INTO peers(name,url,role,description,created_at) VALUES (?,?,?,?,?)",
            (p.name, p.url, p.role, p.description, int(time.time())),
        )
        return {"peer_id": rid, "name": p.name}

    @app.get("/api/peers")
    async def peers(role: str | None = None):
        """已登记的 PT 列表(可按 role 过滤)。"""
        if role:
            rows = db.query("SELECT * FROM peers WHERE role=?", (role,))
        else:
            rows = db.query("SELECT * FROM peers")
        return [_peer_row(r) for r in rows]

    @app.get("/api/peers/{peer_id}")
    async def peer(peer_id: int):
        row = db.query("SELECT * FROM peers WHERE id=?", (peer_id,))
        if not row:
            raise HTTPException(404, "peer not found")
        return _peer_row(row[0])

    @app.post("/api/join-request")
    async def join_request(req: JoinRequestIn):
        """组员向组长发起加入团队申请。"""
        rid = db.insert(
            "INSERT INTO requests(peer_id,peer_name,peer_url,leader_id,status,created_at)"
            " VALUES (?,?,?,?, 'pending', ?)",
            (req.peer_id, req.peer_name, req.peer_url, req.leader_id, int(time.time())),
        )
        return {"request_id": rid, "status": "pending"}

    @app.get("/api/requests")
    async def requests(leader_id: int, status: str | None = None):
        """组长查询收到的申请(可过滤 status)。"""
        if status:
            rows = db.query(
                "SELECT * FROM requests WHERE leader_id=? AND status=? ORDER BY id DESC",
                (leader_id, status),
            )
        else:
            rows = db.query(
                "SELECT * FROM requests WHERE leader_id=? ORDER BY id DESC", (leader_id,)
            )
        return rows

    @app.post("/api/approve")
    async def approve(req: ApproveIn):
        """组长批准/拒绝组员加入申请。"""
        rows = db.query("SELECT * FROM requests WHERE id=?", (req.request_id,))
        if not rows:
            raise HTTPException(404, "request not found")
        new_status = "approved" if req.approve else "rejected"
        db.execute(
            "UPDATE requests SET status=?, decided_at=? WHERE id=?",
            (new_status, int(time.time()), req.request_id),
        )
        return {"request_id": req.request_id, "status": new_status}

    @app.get("/api/approved")
    async def approved(leader_id: int):
        """组长已批准的组员列表(用于动态注册 A2AAdapter)。"""
        rows = db.query(
            "SELECT * FROM requests WHERE leader_id=? AND status='approved'",
            (leader_id,),
        )
        return [
            {
                "request_id": r["id"],
                "peer_id": r["peer_id"],
                "name": r["peer_name"],
                "url": r["peer_url"],
            }
            for r in rows
        ]

    return app


def build_db(path: Path | str) -> Database:
    return Database(path)
