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
from task_orchestrator.adapters.retrieval_adapter import RetrievalAdapter
from task_orchestrator.common.config import get_settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时向注册中心登记本实例;组长则拉取一次已批准组员并启动定时刷新。"""
    global _instance_peer_id
    settings = get_settings()
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
    if settings.codex_cli_enabled:
        approval_mode = settings.codex_approval_mode
        # sandbox 跟随审批模式:auto 收窄到 workspace-write(避免随意触发 UAC),
        # 仅 full(明确信任)才绕过 sandbox
        sandbox = "danger-full-access" if approval_mode == "full" else "workspace-write"
        adapter = CodexCliAdapter(
            workdir=settings.codex_cli_workdir,
            model=None,  # 用 CODEX_HOME config.toml 的模型,不强制覆盖
            sandbox=sandbox,
            approval_mode=approval_mode,
            codex_cmd=settings.codex_cli_cmd,
            codex_home=settings.codex_cli_home,
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
    registry = build_registry(model, role=settings.a2a_role, dynamic_peers=(settings.a2a_role == "leader"))
    graph = build_main_agent(model, registry, role=settings.a2a_role)

    config = {"configurable": {"thread_id": session_id or uuid.uuid4().hex}}
    sid = session_id or config["configurable"]["thread_id"]

    # 对注册的 A2A / retrieval 适配器做异步 connect(连接成功才可用)
    for name in list(registry.list_all()):
        if name["type"] not in ("a2a", "retrieval"):
            continue
        adapter = registry.get(name["name"])
        if adapter and hasattr(adapter, "connect") and not adapter.is_available:
            await adapter.connect()

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
