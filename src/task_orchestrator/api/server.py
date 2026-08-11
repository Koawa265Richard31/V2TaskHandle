"""FastAPI SSE 服务:连接前端与 LangGraph Main Agent。"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from task_orchestrator.adapters.a2a_adapter import A2AAdapter
from task_orchestrator.adapters.codex_adapter import MockCodexAdapter
from task_orchestrator.adapters.codex_cli_adapter import CodexCliAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.adapters.mcp_adapter import McpAgentAdapter
from task_orchestrator.adapters.retrieval_adapter import RetrievalAdapter
from task_orchestrator.common.config import get_settings
from task_orchestrator.common.db import Database
from task_orchestrator.common.llm import build_chat_model
from task_orchestrator.main_agent.graph import build_main_agent
from task_orchestrator.registry import AgentRegistry
from task_orchestrator.registry_client import RegistryClient, register_instance

logger = logging.getLogger("api")

# 从注册中心拉取的已批准组员缓存(dynamic_peers 用),形如 [{name,url}, ...]
_approved_peers_cache: list[dict] = []
# 本实例在注册中心的 peer_id(启动注册后填入)
_instance_peer_id: int | None = None

# 会话状态存储:session_id → {task_plan, role, ts}
# 用于 waiting_approval 任务的审批/改策略重跑(前端操作后重新 submit)
_sessions: dict[str, dict] = {}

# 组长定时刷新已批准组员的后台任务控制
_refresh_stop: asyncio.Event = asyncio.Event()
_refresh_task: asyncio.Task | None = None

# 运行时 codex 配置(用户在界面指定,覆盖 .env;SQLite 持久化)
_runtime_codex: dict[str, str] = {}
_codex_db: Database | None = None

# 运行时外部 Agent 配置(用户通过界面动态注册,SQLite 持久化)
_runtime_external_agents: list[dict] = []
_external_agents_db: Database | None = None

_CODEX_CONFIG_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS codex_config ("
    "  key TEXT PRIMARY KEY,"
    "  value TEXT NOT NULL"
    ")",
]

_EXTERNAL_AGENTS_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS external_agents ("
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  name TEXT NOT NULL UNIQUE,"
    "  base_url TEXT NOT NULL,"
    "  api_key TEXT NOT NULL DEFAULT '',"
    "  capability TEXT NOT NULL DEFAULT 'retrieve',"
    "  agent_type TEXT NOT NULL DEFAULT 'retrieval',"
    "  created_at TEXT NOT NULL DEFAULT (datetime('now'))"
    ")",
]


def _load_codex_config(db: Database) -> dict[str, str]:
    """从 db 加载运行时 codex 配置。"""
    result: dict[str, str] = {}
    for row in db.query("SELECT key, value FROM codex_config"):
        result[row["key"]] = row["value"]
    return result


def _save_codex_config(db: Database, key: str, value: str) -> None:
    """写入/更新单个 codex 配置项。"""
    existing = db.query("SELECT value FROM codex_config WHERE key=?", (key,))
    if existing:
        db.execute("UPDATE codex_config SET value=? WHERE key=?", (value, key))
    else:
        db.insert("INSERT INTO codex_config(key, value) VALUES (?, ?)", (key, value))


# ── 运行时外部 Agent 持久化辅助函数 ──────────────────────────

def _load_external_agents(db: Database) -> list[dict]:
    return db.query("SELECT * FROM external_agents ORDER BY id")


def _save_external_agent(db: Database, name: str, base_url: str, api_key: str, capability: str, agent_type: str) -> int:
    return db.insert(
        "INSERT INTO external_agents(name, base_url, api_key, capability, agent_type) VALUES (?,?,?,?,?)",
        (name, base_url, api_key, capability, agent_type),
    )


def _delete_external_agent(db: Database, name: str) -> int:
    return db.execute("DELETE FROM external_agents WHERE name=?", (name,))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时向注册中心登记本实例;组长则拉取一次已批准组员并启动定时刷新。"""
    global _instance_peer_id, _codex_db, _runtime_codex, _external_agents_db, _runtime_external_agents
    settings = get_settings()
    # 运行时配置持久化(codex + 外部 Agent)
    _codex_db = Database(settings.db_path("runtime_config"))
    _codex_db.migrate("codex_config_v1", _CODEX_CONFIG_SCHEMA)
    _runtime_codex = _load_codex_config(_codex_db)
    _external_agents_db = Database(settings.db_path("runtime_config"))
    _external_agents_db.migrate("external_agents_v1", _EXTERNAL_AGENTS_SCHEMA)
    _runtime_external_agents = _load_external_agents(_external_agents_db)
    if settings.registry_url:
        url = f"http://{settings.bind_host}:{settings.api_port}"
        try:
            peer_id = await register_instance(settings, url)
            if peer_id is not None:
                _instance_peer_id = peer_id
                if settings.a2a_role == "leader":
                    await _refresh_approved(settings)
                    if settings.peer_refresh_seconds > 0:
                        _start_refresh_loop(settings.peer_refresh_seconds, settings)
        except Exception as exc:
            logger.warning("启动注册失败", extra={"error": str(exc)})
    yield
    _stop_refresh_loop()
    _instance_peer_id = None
    if _codex_db is not None:
        _codex_db.close()
        _codex_db = None
    if _external_agents_db is not None:
        _external_agents_db.close()
        _external_agents_db = None


app = FastAPI(title="Task Orchestrator API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequestBody(BaseModel):
    message: str = ""
    session_id: str | None = None


def build_registry(model=None, role: str = "leader", dynamic_peers: bool = False,
                   settings=None) -> AgentRegistry:
    """构造 Agent 注册表。

    role=leader:注册 A2A 适配器(可向组员下发任务)。
    role=member:不注册 A2A 适配器(结构上禁止向其他 agent 下发)。
    dynamic_peers=True:从注册中心拉取已批准组员,动态注册为 A2AAdapter(组长)。
    settings 可显式注入(测试用),默认取进程级 get_settings()。
    """
    settings = settings or get_settings()
    registry = AgentRegistry()

    # 仅组长可向组员下发任务
    if role == "leader":
        # 静态配置的 A2A agents
        for agent_cfg in settings.a2a_agents:
            adapter = A2AAdapter(agent_cfg.url, agent_cfg.api_key, timeout=settings.a2a_timeout)
            registry.register(adapter, agent_cfg.name or f"a2a_{agent_cfg.url}")

        # 从注册中心已拉取的批准组员(由 _refresh_approved 更新缓存)
        if dynamic_peers:
            for peer in _approved_peers_cache:
                adapter = A2AAdapter(peer["url"], settings.a2a_api_key, timeout=settings.a2a_timeout)
                registry.register(adapter, peer["name"] or f"a2a_{peer['url']}")

    # Codex(Mock 或真实 SDK)
    registry.register(MockCodexAdapter(mock_results={"default": "Codex 模拟执行完成"}), "codex")

    # 本机 codex CLI(注册现成 coding agent,capability=code)
    if settings.codex_cli_enabled or _runtime_codex:
        approval_mode = settings.codex_approval_mode
        # sandbox 跟随审批模式:auto 收窄到 workspace-write(避免随意触发 UAC),
        # 仅 full(明确信任)才绕过 sandbox
        sandbox = "danger-full-access" if approval_mode == "full" else "workspace-write"
        # 运行时配置(界面指定)优先于 .env
        codex_cmd = _runtime_codex.get("codex_cmd") or settings.codex_cli_cmd
        codex_home = _runtime_codex.get("codex_home") or settings.codex_cli_home
        adapter = CodexCliAdapter(
            workdir=settings.codex_cli_workdir,
            model=None,  # 用 CODEX_HOME config.toml 的模型,不强制覆盖
            sandbox=sandbox,
            approval_mode=approval_mode,
            codex_cmd=codex_cmd,
            codex_home=codex_home,
        )
        registry.register(adapter, "codex_cli")

    # 远端 REST 垂类 Agent(如检索):从配置注册,connect 成功才可用
    for agent_cfg in settings.external_agents:
        adapter = RetrievalAdapter(
            base_url=agent_cfg.base_url,
            api_key=agent_cfg.api_key,
            timeout=settings.a2a_timeout,
        )
        name = agent_cfg.name or agent_cfg.base_url
        registry.register(adapter, name)

    # 运行时注册的外部 Agent(SQLite 持久化),与 .env 静态配置共存
    for agent_cfg in _runtime_external_agents:
        agent_type = agent_cfg.get("agent_type", "retrieval")
        base_url = agent_cfg.get("base_url", "")
        api_key = agent_cfg.get("api_key", "")
        name = agent_cfg.get("name", "") or base_url
        if agent_type == "mcp":
            adapter = McpAgentAdapter(
                base_url=base_url,
                api_key=api_key,
                timeout=settings.a2a_timeout,
            )
        else:
            adapter = RetrievalAdapter(
                base_url=base_url,
                api_key=api_key,
                timeout=settings.a2a_timeout,
            )
        # 同步注册(异步 connect 在 _connect_external helper 中)
        registry.register(adapter, name)

    def _connect_external(registry: AgentRegistry) -> None:
        """同步 helper:注册后尝试 connect(仅登记,连接在 event_stream 中完成)。"""
        pass  # 连接在 event_stream 里 await adapter.connect() 完成,同步上下文无法 await

    _connect_external(registry)

    # 本地工具 Agent(注入 LLM 以便真实执行)
    local = LocalAdapter(
        enabled_tools=settings.local_tool_list or ["shell", "file", "web"],
        model=model,
    )
    registry.register(local, "local")

    return registry


def sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def event_stream(message: str, session_id: str | None, model=None):
    model = model or build_chat_model()
    settings = get_settings()

    # 先 build 基础 registry(含未 connect 的 retrieval/mcp),然后 connect,再注入给 graph
    registry = build_registry(model, role=settings.a2a_role, dynamic_peers=(settings.a2a_role == "leader"))

    # 对已注册的 retrieval / mcp adapter 做异步 connect(连接成功后 is_available 变 True)
    connect_ok: list[str] = []
    for name in list(registry.list_all()):
        if name["type"] not in ("a2a", "retrieval", "mcp"):
            continue
        adapter = registry.get(name["name"])
        if adapter and hasattr(adapter, "connect") and not adapter.is_available:
            await adapter.connect()
            logger.info("Adapter connected", extra={"name": name["name"], "type": name["type"], "available": adapter.is_available})
            if adapter.is_available:
                connect_ok.append(name["name"])

    # 构建 extra_context:若 retrieval agent 已连接,明确提示 LLM 使用它
    extra_context = ""
    if connect_ok:
        extra_context = "\n注意:以下 retrieval/mcp agent 已经连接成功可以使用: " + ", ".join(connect_ok)

    graph = build_main_agent(model, registry, role=settings.a2a_role, extra_context=extra_context)

    config = {"configurable": {"thread_id": session_id or uuid.uuid4().hex}}
    sid = session_id or config["configurable"]["thread_id"]

    yield sse("message", {"delta": "正在分析你的请求..."})

    prev_plan: list[dict] = []
    final_response: str | None = None
    try:
        async for ev in graph.astream_events(
            {
                "messages": [HumanMessage(content=message)],
                "user_request": "",
                "task_plan": [],
                "final_response": "",
            },
            config,
            version="v2",
        ):
            kind = ev["event"]
            name = ev.get("name", "")
            if kind != "on_chain_end" or name not in ("plan", "dispatch", "monitor", "replan", "aggregate"):
                continue
            output = ev.get("data", {}).get("output", {})
            if not isinstance(output, dict):
                continue
            plan = output.get("task_plan") or []
            if not plan:
                if name == "aggregate" and output.get("final_response"):
                    final_response = output["final_response"]
                continue

            if name == "plan":
                # 计划生成:先广播任务列表
                yield sse("plan", {"tasks": plan})

            # 对比上一轮状态,发出增量事件
            for delta in _emit_task_deltas(prev_plan, plan):
                yield delta
            prev_plan = copy.deepcopy(plan)
    except asyncio.TimeoutError:
        yield sse("error", {"message": "请求超时,请重试"})
    except Exception as exc:
        logger.exception("Graph execution failed")
        err = str(exc)[:300]
        yield sse("error", {"message": f"执行失败: {err}"})

    if final_response:
        for i in range(0, len(final_response), 5):
            yield sse("message", {"delta": final_response[i:i + 5]})

    # 保存会话任务状态(供 waiting_approval 审批/改策略)
    _sessions[sid] = {
        "task_plan": copy.deepcopy(prev_plan),
        "role": settings.a2a_role,
        "ts": asyncio.get_running_loop().time(),
    }

    yield sse("done", {"final_response": final_response, "session_id": sid})


def _emit_task_deltas(prev: list[dict], curr: list[dict]):
    """对比前后 task_plan,发出 task_start/task_update/task_complete/task_fail/task_waiting_approval。
    新出现且非 running 的任务不发事件(其状态已包含在 plan 事件里)。"""
    prev_map = {t["task_id"]: t for t in prev}
    for task in curr:
        tid = task["task_id"]
        status = task.get("status", "pending")
        before = prev_map.get(tid)
        before_status = before.get("status") if before else None

        if before is None:
            # 新任务:只有开始执行(running)才单独广播 task_start
            if status == "running":
                yield sse("task_start", {
                    "task_id": tid,
                    "agent_type": task.get("agent_type"),
                    "approval_mode": task.get("approval_mode", "auto"),
                    "requires_monitor": task.get("requires_monitor", False),
                })
            continue
        if before_status != status:
            if status == "completed" and task.get("result"):
                yield sse("task_complete", {
                    "task_id": tid,
                    "result": task["result"],
                    "progress": task.get("progress"),
                })
            elif status == "failed" and task.get("error"):
                yield sse("task_fail", {
                    "task_id": tid,
                    "error": task["error"],
                    "progress": task.get("progress"),
                })
            elif status == "waiting_approval":
                yield sse("task_waiting_approval", {
                    "task_id": tid,
                    "message": task.get("error") or task.get("progress") or "等待人工审批",
                    "approval_mode": task.get("approval_mode", "auto"),
                })
            else:
                yield sse("task_update", {
                    "task_id": tid,
                    "status": status,
                    "progress": task.get("progress"),
                    "approval_mode": task.get("approval_mode", "auto"),
                })
        elif before_status == status == "running":
            # running 期间进度文本变化 → task_progress
            bp = before.get("progress")
            cp = task.get("progress")
            if cp and cp != bp:
                yield sse("task_progress", {
                    "task_id": tid,
                    "progress": cp,
                })


@app.post("/api/chat")
async def chat(body: ChatRequestBody):
    return StreamingResponse(
        event_stream(body.message, body.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/agents")
async def list_agents():
    settings = get_settings()
    return build_registry(role=settings.a2a_role, dynamic_peers=(settings.a2a_role == "leader")).list_all()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


class TaskApproveBody(BaseModel):
    session_id: str
    task_id: str
    approval_mode: str = "auto"  # 仅 retry_with_approval 用:full / auto


async def _get_session_task(session_id: str, task_id: str) -> tuple[dict, dict]:
    """按 session_id + task_id 取 (session, task)。找不到抛 HTTPException。"""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "会话不存在或已过期")
    task = next(
        (t for t in session.get("task_plan", []) if str(t.get("task_id")) == str(task_id)),
        None,
    )
    if not task:
        raise HTTPException(404, f"任务 {task_id} 不在该会话中")
    return session, task


@app.post("/api/tasks/{task_id}/retry_with_approval")
async def api_retry_with_approval(task_id: str, body: TaskApproveBody):
    """waiting_approval 任务:改策略重跑。前端改 full/auto 后重新 submit 给 codex。

    - 修改任务 approval_mode
    - 重新 submit(原 description 或切片 prompt 发给 codex)
    - 任务回 running,前端轮询/刷新看到新状态
    """
    session, task = await _get_session_task(body.session_id, task_id)
    if task.get("status") != "waiting_approval":
        return {"ok": False, "error": f"任务当前状态 {task.get('status')},非 waiting_approval"}

    new_mode = body.approval_mode if body.approval_mode in ("full", "auto") else "auto"
    task["approval_mode"] = new_mode

    settings = get_settings()
    registry = build_registry(role=session.get("role", settings.a2a_role),
                              dynamic_peers=(session.get("role") == "leader"))
    adapter = registry.get_by_type(task.get("agent_type", "codex_cli"))
    if not adapter:
        return {"ok": False, "error": f"无 {task.get('agent_type')} 适配器"}

    try:
        ext_id = task.get("external_id")
        if ext_id and hasattr(adapter, "resume"):
            # 有原 codex 会话 → resume 恢复(保留上下文)
            try:
                await adapter.resume(ext_id, task.get("description", ""))
            except Exception as resume_exc:
                logger.warning("resume 失败,重新 submit", extra={"error": str(resume_exc)})
                ext_id = await adapter.submit(task)
        else:
            # 无 external_id 或 adapter 不支持 resume → 重新 submit
            ext_id = await adapter.submit(task)
        task["status"] = "running"
        task["external_id"] = ext_id
        task["error"] = None
        # 清理 codex 侧的等待审批标记(如 adapter 支持)
        if hasattr(adapter, "_waiting_approval"):
            adapter._waiting_approval.pop(ext_id, None)
        return {"ok": True, "task_id": task_id, "status": "running", "approval_mode": new_mode}
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)
        return {"ok": False, "error": str(exc)}


@app.post("/api/tasks/{task_id}/approve")
async def api_approve_task(task_id: str, body: TaskApproveBody):
    """auto 模式:批准等待审批的任务继续执行。

    语义=重新 submit 同一任务(codex 重跑,多数情况下 auto 下受限项能通过),
    与 retry_with_approval 的区别是不改策略。
    """
    session, task = await _get_session_task(body.session_id, task_id)
    if task.get("status") != "waiting_approval":
        return {"ok": False, "error": f"任务当前状态 {task.get('status')},非 waiting_approval"}

    settings = get_settings()
    registry = build_registry(role=session.get("role", settings.a2a_role),
                              dynamic_peers=(session.get("role") == "leader"))
    adapter = registry.get_by_type(task.get("agent_type", "codex_cli"))
    if not adapter:
        return {"ok": False, "error": f"无 {task.get('agent_type')} 适配器"}

    try:
        ext_id = task.get("external_id")
        if ext_id and hasattr(adapter, "resume"):
            try:
                await adapter.resume(ext_id, task.get("description", ""))
            except Exception as resume_exc:
                logger.warning("resume 失败,重新 submit", extra={"error": str(resume_exc)})
                ext_id = await adapter.submit(task)
        else:
            ext_id = await adapter.submit(task)
        task["status"] = "running"
        task["external_id"] = ext_id
        task["error"] = None
        if hasattr(adapter, "_waiting_approval"):
            adapter._waiting_approval.pop(ext_id, None)
        return {"ok": True, "task_id": task_id, "status": "running"}
    except Exception as exc:
        task["status"] = "failed"
        task["error"] = str(exc)
        return {"ok": False, "error": str(exc)}


# ── 注册中心集成(云端 PT 协作) ──────────────────────────────────


def _registry_url() -> str:
    return get_settings().registry_url


async def _refresh_approved(settings=None) -> list[dict]:
    """组长:从注册中心拉取已批准组员,更新缓存。"""
    global _approved_peers_cache
    settings = settings or get_settings()
    if not settings.registry_url or not _instance_peer_id:
        return _approved_peers_cache
    client = RegistryClient(settings.registry_url)
    try:
        _approved_peers_cache = await client.approved_peers(_instance_peer_id)
    except Exception as exc:
        logger.warning("拉取已批准组员失败", extra={"error": str(exc)})
    finally:
        await client.close()
    return _approved_peers_cache


def _start_refresh_loop(interval: float, settings=None) -> None:
    """组长:启动后台定时刷新任务。仅在 lifespan 中 role=leader 且 interval>0 时调用。"""
    global _refresh_task
    _refresh_stop.clear()
    _refresh_task = asyncio.create_task(_peer_refresh_loop(interval, settings))


def _stop_refresh_loop() -> None:
    """停止定时刷新任务(lifespan 退出时调用)。"""
    global _refresh_task
    _refresh_stop.set()
    if _refresh_task is not None:
        _refresh_task.cancel()
        _refresh_task = None


async def _peer_refresh_loop(interval: float, settings=None) -> None:
    """每 interval 秒刷新一次已批准组员缓存;收到停止信号立即退出。"""
    settings = settings or get_settings()
    while True:
        try:
            # wait_for:interval 到点 → TimeoutError → 刷新;stop 置位 → 立即返回
            await asyncio.wait_for(_refresh_stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await _refresh_approved(settings)
        except Exception:
            logger.exception("定时刷新已批准组员失败")


@app.get("/api/peers")
async def api_peers():
    """查看本实例的注册/申请状态(供前端面板)。"""
    settings = get_settings()
    result = {
        "registered": _instance_peer_id is not None,
        "peer_id": _instance_peer_id,
        "role": settings.a2a_role,
        "name": settings.instance_name,
        "registry_url": settings.registry_url,
        "approved_peers": list(_approved_peers_cache),
        "requests": [],
    }
    if settings.registry_url and _instance_peer_id and settings.a2a_role == "leader":
        client = RegistryClient(settings.registry_url)
        try:
            result["requests"] = await client.list_requests(_instance_peer_id, status="pending")
            result["approved_peers"] = await _refresh_approved(settings)
        except Exception as exc:
            logger.warning("查询注册中心失败", extra={"error": str(exc)})
        finally:
            await client.close()
    return result


class JoinRequestBody(BaseModel):
    leader_id: int


@app.post("/api/join-request")
async def api_join_request(body: JoinRequestBody):
    """组员:向组长发起加入团队申请。"""
    settings = get_settings()
    if not settings.registry_url:
        return {"ok": False, "error": "未配置注册中心 (PTA_REGISTRY_URL)"}
    if _instance_peer_id is None:
        return {"ok": False, "error": "尚未注册到注册中心"}
    # 组员对外提供的是 A2A 服务(a2a_port),组长通过它下发
    a2a_url = f"http://{settings.bind_host}:{settings.a2a_port}"
    client = RegistryClient(settings.registry_url)
    try:
        rid = await client.join_request(
            _instance_peer_id, settings.instance_name, a2a_url, body.leader_id
        )
        return {"ok": True, "request_id": rid}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await client.close()


class ApproveBody(BaseModel):
    request_id: int
    approve: bool = True


# ── 身份管理 ─────────────────────────────────────────


class IdentityBody(BaseModel):
    name: str
    role: str = "member"  # leader | member


@app.get("/api/identity")
async def api_get_identity():
    """返回当前实例的身份信息。"""
    settings = get_settings()
    return {
        "name": settings.instance_name,
        "role": settings.a2a_role,
        "peer_id": _instance_peer_id,
        "registry_url": settings.registry_url,
    }


@app.put("/api/identity")
async def api_put_identity(body: IdentityBody):
    """更新实例名和角色。角色切换需告知前端重启后端。"""
    settings = get_settings()
    old_role = settings.a2a_role
    settings.instance_name = body.name.strip() or settings.instance_name
    settings.a2a_role = body.role if body.role in ("leader", "member") else settings.a2a_role
    return {
        "ok": True,
        "name": settings.instance_name,
        "role": settings.a2a_role,
        "role_changed": old_role != settings.a2a_role,
    }


# ── 邀请码 ───────────────────────────────────────────


@app.get("/api/team/invite-code")
async def api_get_invite_code():
    """组长:获取邀请码。非组长返回空。"""
    settings = get_settings()
    if settings.a2a_role != "leader" or _instance_peer_id is None:
        return {"invite_code": "", "error": "仅组长可获取邀请码"}
    if not settings.registry_url:
        return {"invite_code": "", "error": "未配置注册中心"}
    client = RegistryClient(settings.registry_url)
    try:
        code = await client.get_invite_code(_instance_peer_id)
        return {"invite_code": code}
    except Exception as exc:
        return {"invite_code": "", "error": str(exc)}
    finally:
        await client.close()


@app.post("/api/team/invite-code/regenerate")
async def api_regenerate_invite_code():
    """组长:重新生成邀请码。"""
    settings = get_settings()
    if settings.a2a_role != "leader" or _instance_peer_id is None:
        return {"ok": False, "error": "仅组长可操作"}
    if not settings.registry_url:
        return {"ok": False, "error": "未配置注册中心"}
    client = RegistryClient(settings.registry_url)
    try:
        code = await client.regenerate_invite_code(_instance_peer_id)
        return {"ok": True, "invite_code": code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await client.close()


class JoinByCodeBody(BaseModel):
    invite_code: str


@app.post("/api/join-by-code")
async def api_join_by_code(body: JoinByCodeBody):
    """组员:通过邀请码加入组长团队。"""
    settings = get_settings()
    if not settings.registry_url:
        return {"ok": False, "error": "未配置注册中心 (PTA_REGISTRY_URL)"}
    if _instance_peer_id is None:
        return {"ok": False, "error": "尚未注册到注册中心"}
    a2a_url = f"http://{settings.bind_host}:{settings.a2a_port}"
    client = RegistryClient(settings.registry_url)
    try:
        result = await client.join_by_code(
            _instance_peer_id, settings.instance_name, a2a_url, body.invite_code.strip().upper()
        )
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await client.close()


@app.post("/api/approve")
async def api_approve(body: ApproveBody):
    """组长:批准/拒绝组员加入申请。"""
    settings = get_settings()
    if not settings.registry_url:
        return {"ok": False, "error": "未配置注册中心"}
    client = RegistryClient(settings.registry_url)
    try:
        status = await client.approve(body.request_id, body.approve)
        if status == "approved":
            await _refresh_approved(settings)
        return {"ok": True, "status": status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await client.close()


class CodexConfigBody(BaseModel):
    codex_cmd: str = ""
    codex_home: str = ""


@app.get("/api/config/codex")
async def api_get_codex_config():
    """当前 codex 配置:运行时覆盖值优先,否则 .env。"""
    settings = get_settings()
    return {
        "codex_cmd": _runtime_codex.get("codex_cmd") or settings.codex_cli_cmd,
        "codex_home": _runtime_codex.get("codex_home") or settings.codex_cli_home,
        "source": "runtime" if _runtime_codex else "env",
    }


@app.put("/api/config/codex")
async def api_put_codex_config(body: CodexConfigBody):
    """保存运行时 codex 配置(界面指定,持久化到 SQLite)。"""
    global _runtime_codex
    if _codex_db is None:
        return {"ok": False, "error": "配置存储未初始化"}
    _save_codex_config(_codex_db, "codex_cmd", body.codex_cmd.strip())
    _save_codex_config(_codex_db, "codex_home", body.codex_home.strip())
    _runtime_codex = _load_codex_config(_codex_db)
    return {"ok": True, "codex_cmd": _runtime_codex.get("codex_cmd", ""), "codex_home": _runtime_codex.get("codex_home", "")}


@app.post("/api/config/codex/verify")
async def api_verify_codex_config(body: CodexConfigBody):
    """验证指定 codex 路径是否可用(构造 adapter 检查 is_available)。"""
    settings = get_settings()
    adapter = CodexCliAdapter(
        workdir=settings.codex_cli_workdir,
        codex_cmd=body.codex_cmd.strip() or _runtime_codex.get("codex_cmd") or settings.codex_cli_cmd,
        codex_home=body.codex_home.strip() or _runtime_codex.get("codex_home") or settings.codex_cli_home,
    )
    return {
        "ok": adapter.is_available,
        "codex_cmd": adapter.codex_cmd,
        "available": adapter.is_available,
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


# ── 外部 Agent 运行时注册管理 ──────────────────────────────────


class ExternalAgentBody(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    capability: str = "retrieve"
    agent_type: str = "retrieval"  # retrieval | mcp


@app.get("/api/external-agents")
async def api_list_external_agents():
    """列出所有运行时注册的外部 Agent。"""
    return _runtime_external_agents


@app.post("/api/external-agents")
async def api_register_external_agent(body: ExternalAgentBody):
    """注册新的外部 Agent(持久化到 SQLite)。"""
    global _runtime_external_agents
    if not body.name.strip():
        return {"ok": False, "error": "name 不能为空"}
    if not body.base_url.strip():
        return {"ok": False, "error": "base_url 不能为空"}

    existing = [a for a in _runtime_external_agents if a["name"] == body.name.strip()]
    if existing:
        return {"ok": False, "error": f"Agent '{body.name}' 已存在"}

    if _external_agents_db is None:
        return {"ok": False, "error": "配置存储未初始化"}

    row_id = _save_external_agent(
        _external_agents_db,
        body.name.strip(), body.base_url.strip(),
        body.api_key.strip(), body.capability.strip(),
        body.agent_type.strip(),
    )
    _runtime_external_agents = _load_external_agents(_external_agents_db)
    return {"ok": True, "id": row_id, "name": body.name.strip()}


@app.delete("/api/external-agents/{name}")
async def api_delete_external_agent(name: str):
    """删除运行时注册的外部 Agent。"""
    global _runtime_external_agents
    if _external_agents_db is None:
        return {"ok": False, "error": "配置存储未初始化"}
    affected = _delete_external_agent(_external_agents_db, name)
    if affected:
        _runtime_external_agents = _load_external_agents(_external_agents_db)
        return {"ok": True}
    return {"ok": False, "error": f"Agent '{name}' 不存在"}


@app.post("/api/external-agents/{name}/verify")
async def api_verify_external_agent(name: str):
    """验证指定外部 Agent 的连通性(调 /health 或 MCP initialize + tools/list)。"""
    cfg = next((a for a in _runtime_external_agents if a["name"] == name), None)
    if not cfg:
        return {"ok": False, "error": f"Agent '{name}' 不存在"}

    agent_type = cfg.get("agent_type", "retrieval")
    if agent_type == "mcp":
        adapter = McpAgentAdapter(base_url=cfg["base_url"], api_key=cfg.get("api_key", ""))
    else:
        adapter = RetrievalAdapter(base_url=cfg["base_url"], api_key=cfg.get("api_key", ""))

    try:
        available = await adapter.connect()
        tools = getattr(adapter, "_tools", None) or {}
        return {
            "ok": True, "available": available,
            "agent_type": agent_type,
            "tools": list(tools.keys()) if isinstance(tools, dict) else [],
        }
    except Exception as exc:
        return {"ok": False, "available": False, "error": str(exc)}
    finally:
        await adapter.close()
