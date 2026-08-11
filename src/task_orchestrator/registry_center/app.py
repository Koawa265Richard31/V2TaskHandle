"""中央注册中心:PT 实例登记、发现、加入申请、组长批准、邀请码。

跨环境(云端)协作的共享锚点。所有 PT 启动时向这里登记自身(name/url/role),
组员向组长发加入申请,组长(人类)批准后该组员才对组长可见可下发。
支持邀请码:组长注册时自动生成 6 位邀请码,组员通过邀请码加入。
"""

from __future__ import annotations

import random
import string
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
    "  invite_code TEXT DEFAULT '',"
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

CODE_LENGTH = 6
CODE_CHARS = string.ascii_uppercase + string.digits


def _generate_code() -> str:
    return "".join(random.choices(CODE_CHARS, k=CODE_LENGTH))


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


class JoinByCodeIn(BaseModel):
    peer_id: int
    peer_name: str
    peer_url: str
    invite_code: str


class InviteCodeRegenIn(BaseModel):
    peer_id: int


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
        """PT 实例登记,返回 peer_id。组长自动生成邀请码。"""
        invite_code = ""
        if p.role == "leader":
            invite_code = _generate_code()
            # 冲突重试(极低概率)
            for _ in range(5):
                existing = db.query("SELECT id FROM peers WHERE invite_code=?", (invite_code,))
                if not existing:
                    break
                invite_code = _generate_code()
        rid = db.insert(
            "INSERT INTO peers(name,url,role,description,invite_code,created_at) VALUES (?,?,?,?,?,?)",
            (p.name, p.url, p.role, p.description, invite_code, int(time.time())),
        )
        return {"peer_id": rid, "name": p.name, "invite_code": invite_code}

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

    @app.get("/api/invite-code")
    async def invite_code(peer_id: int):
        """组长查询自己的邀请码。如果尚未生成则自动生成。"""
        rows = db.query("SELECT * FROM peers WHERE id=?", (peer_id,))
        if not rows:
            raise HTTPException(404, "peer not found")
        code = rows[0].get("invite_code", "")
        if not code and rows[0]["role"] == "leader":
            code = _generate_code()
            for _ in range(5):
                existing = db.query("SELECT id FROM peers WHERE invite_code=?", (code,))
                if not existing:
                    break
                code = _generate_code()
            db.execute("UPDATE peers SET invite_code=? WHERE id=?", (code, peer_id))
        return {"peer_id": peer_id, "invite_code": code}

    @app.post("/api/invite-code/regenerate")
    async def regenerate_invite_code(body: InviteCodeRegenIn):
        """组长重新生成邀请码。"""
        rows = db.query("SELECT * FROM peers WHERE id=?", (body.peer_id,))
        if not rows:
            raise HTTPException(404, "peer not found")
        if rows[0]["role"] != "leader":
            raise HTTPException(400, "仅组长可重新生成邀请码")
        new_code = _generate_code()
        for _ in range(5):
            existing = db.query("SELECT id FROM peers WHERE invite_code=?", (new_code,))
            if not existing:
                break
            new_code = _generate_code()
        db.execute("UPDATE peers SET invite_code=? WHERE id=?", (new_code, body.peer_id))
        return {"peer_id": body.peer_id, "invite_code": new_code}

    @app.post("/api/join-by-code")
    async def join_by_code(req: JoinByCodeIn):
        """组员通过邀请码加入:自动解析 leader_id 并发起申请。"""
        rows = db.query("SELECT * FROM peers WHERE invite_code=?", (req.invite_code,))
        if not rows:
            raise HTTPException(404, "无效的邀请码")
        leader = rows[0]
        if leader["role"] != "leader":
            raise HTTPException(400, "该邀请码不属于组长")
        rid = db.insert(
            "INSERT INTO requests(peer_id,peer_name,peer_url,leader_id,status,created_at)"
            " VALUES (?,?,?,?, 'pending', ?)",
            (req.peer_id, req.peer_name, req.peer_url, leader["id"], int(time.time())),
        )
        return {"request_id": rid, "status": "pending", "leader_id": leader["id"], "leader_name": leader["name"]}

    return app


def build_db(path: Path | str) -> Database:
    return Database(path)
