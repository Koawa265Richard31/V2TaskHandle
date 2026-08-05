# 实现规划书：SubAgent 编排与两级 Agent 架构（v2 对 v2）

> 状态：规划阶段
> 前置文档：[06_PLAN_v2.md](06_PLAN_v2.md)、[08_AGENT_TO_AGENT.md](08_AGENT_TO_AGENT.md)、[AUDIT.md](AUDIT.md)
> 日期：2026-08-04
> 决策来源：用户口头确认的架构决策

---

## 1. 目标

### 1.1 一句话定义

把 v2 Main Agent 从「按 agent_type 三选一」的规划器，升级为**两级编排器**：本机 TaskAgent（唯一编排器）通过 **REST** 调用远端垂类 agent（检索等），通过 **A2A 1.0** 调用本机其他 coding agent；每完成一个子任务即送**独立审查**，最多三次重试，未通过则给出审查不通过原因。

### 1.2 用户核心决策（本次定稿）

| 决策点 | 结论 |
|--------|------|
| 审查粒度 | **每个子任务完成后独立审查**（进入 monitor 循环），不是全部完成后统一审 |
| 远端检索 agent 调用 | **异步任务队列**：`POST /tasks` 拿 task_id → 轮询 `GET /tasks/{id}` → 完成后拉结果 |
| 远端 vs 本机通信 | **远端垂类 agent = REST**（公网访问，不在 PT 同一台设备）；**本机 agent = A2A 1.0** |
| coding agent | **注册现成的 Claude Code / Codex**，不独立实现 codingAgent；走本机 adapter 薄封装（复刻 codex_adapter） |
| 审查验收标准 | LLM 对比「子任务要求 vs 结果」判定通过/不通过；**最多 3 次重试**，3 次未通过则记录「审查不通过原因」并标失败 |

### 1.3 与现有架构的关系

- 复用全部现有节点：understand → plan → dispatch → monitor → [replan] → aggregate
- 复用 `BaseAdapter` 统一接口、`AgentRegistry`、`A2AAdapter`、`LocalAdapter`、`LangGraphAgentExecutor`
- 新增：`RetrievalAdapter`（REST）、`review` 图节点、能力路由层、远端 REST 注册机制

---

## 2. 两级架构总览

```
用户发布任务
  └─ TaskAgent（本机唯一编排器 = 现有 Main Agent 图）
       ├─ 检索子任务 → RetrievalAdapter(新增, REST)
       │      POST https://<远端>/tasks + Bearer → task_id
       │      monitor 轮询 GET /tasks/{id} → 完成拉结果(摘要)
       ├─ code 子任务  → 注册的 coding agent（Claude Code / Codex）
       │      本机:  LocalAdapter / CodexAdapter（薄封装，不复现 codingAgent）
       │      远端:  A2AAdapter（若 coding agent 是另一台机）
       ├─ work 子任务  → LocalAdapter（注册文档工具）
       └─ 每子任务完成 → review 节点(新增): LLM 对比"任务要求 vs 结果"
             通过 → 标 completed，进 aggregate
             不通过 → 回 replan 重试（≤3 次），3 次未过 → 标审查不通过原因
       → aggregate 汇总 → 右侧任务栏标记完成结果
```

---

## 3. 通信边界：远端 REST vs 本机 A2A

### 3.1 判定标准

| 维度 | 远端垂类 agent（REST） | 本机 agent（A2A 1.0） |
|------|------------------------|------------------------|
| 部署位置 | 公网，不在 PT 同一台设备 | 与 PT 同机（独立进程/服务） |
| 协议 | 自定义 REST（异步 task 队列） | A2A 1.0 JSON-RPC |
| 调用模式 | `POST /tasks` → task_id → `GET /tasks/{id}` 轮询 | `send_message` 流式 / `get_task` 轮询 |
| 发现 | registry_center 注册/拉取 | AgentCard `/.well-known/agent-card.json` |
| 认证 | `Authorization: Bearer <token>` | `X-API-Key` |
| 谁接入 | 未来各类垂类 agent（医院医疗、法律、垂直搜索等） | Claude Code、Codex、其他本机 PT |

### 3.2 为何远端用 REST 不用 A2A

A2A 1.0 是通用 agent 间协议，要求对方实现完整 A2A 服务端（AgentCard + JSON-RPC + task store）。垂类 agent 通常只暴露业务 API（如医院的问诊/挂号接口），不承载 A2A 语义。REST 只约定「任务提交 + 轮询 + 结果」，接入成本低，也便于第三方开放注册。

---

## 4. 详细设计

### 4.1 新增 `RetrievalAdapter`（`src/task_orchestrator/adapters/retrieval_adapter.py`）

**接口**（实现 `BaseAdapter`，复刻 `A2AAdapter` 的 `_pending` 后台任务模式）：

```python
class RetrievalAdapter(BaseAdapter):
    """远端 REST 垂类 agent 适配器。submit 提交异步任务,monitor 轮询。"""
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0):
        ...
    async def connect(self) -> None:  # 探测 GET /agent-card 或 /health,校验认证
    async def submit(self, task: dict) -> str:
        # POST {base_url}/tasks  {"query": ..., "params": ...}  + Bearer
        #   → 响应 {task_id: "..."}  返回该 task_id
    async def status(self, external_id: str) -> str:
        # GET {base_url}/tasks/{id}  → {"status": "completed|working|failed"}
    async def result(self, external_id: str) -> str | None:
        # GET {base_url}/tasks/{id}/result  → {"content": "..."}  取摘要
    async def cancel(self, external_id: str) -> bool:
        # DELETE {base_url}/tasks/{id}  尽力而为
```

**与 A2AAdapter 的关键差异**：`status/result` 是**主动轮询远端 HTTP**，不是查本地 `_pending` 后台任务。因为远端是独立的异步任务队列，本地只是发任务 + 拉结果。

### 4.2 能力路由层（替代「agent_type 三选一」）

**问题**：现有 `registry.get_by_type("a2a")` 只按类型查，多个同类 agent 共存、同一 agent 多能力都无法表达。

**方案**：给 adapter 增加 `name` + `capabilities`，plan 输出改为「能力名 + 目标」：

```python
# adapters/base.py 增加
@property
def name(self) -> str: ...          # 实例名,如 "retrieval-medical"
@property
def capabilities(self) -> list[str]: ...  # 如 ["retrieve"], ["code"], ["doc"]
```

`AgentRegistry` 增加按能力查询：

```python
def get_by_capability(self, capability: str) -> BaseAdapter | None:
    for adapter in self._adapters.values():
        if capability in adapter.capabilities and adapter.is_available:
            return adapter
    return None
```

plan 输出的 `agent_type` 语义从「a2a/codex/local」升级为「capability 名」（`retrieve/code/doc`），dispatch 时按能力解析。这样新增一个检索 agent，改注册不改调度代码。

### 4.3 coding agent「注册不是实现」

你的判断正确：code 子任务**不实现 codingAgent**，只注册现成的。

- **本机 Claude Code / Codex**：现有 `CodexAdapter` 已是「SDK 封装」，够用。若要接 Claude Code CLI，写一个 `ClaudeCodeAdapter` 复刻它的 `submit/status/result`（shell 调 `claude -p "<prompt>"` 后台跑）。
- **远端 coding agent**（另一台机）：走 `A2AAdapter`，天然支持 task_id + 轮询。
- 无论走哪条，图侧只认 `capability="code"`，实现细节藏在 adapter 里。

### 4.4 每子任务独立审查（新增 review 节点）

**位置**：进 `monitor_node` 循环内。`monitor_node` 现在收集到 `completed` 就结束；改为「adapter 返回 completed → 先送 review，通过才标 completed，否则标 failed 待重试」。

**改动**（`src/task_orchestrator/main_agent/exec_nodes.py`）：

```python
REVIEW_PROMPT = """你是子任务审查员。对比「子任务要求」与「执行结果」,判断子任务是否真正完成。
规则:
1. 结果缺失、明显不相关、格式不对 → 不通过
2. 只输出:  PASS  或  FAIL <简短原因>
"""

async def review_node(task: dict, *, model: BaseChatModel) -> bool:
    """LLM 对比要求 vs 结果,返回是否通过。"""
    result = await model.ainvoke([
        SystemMessage(content=REVIEW_PROMPT),
        HumanMessage(content=f"子任务要求:{task['description']}\n执行结果:{task.get('result')}"),
    ])
    return str(result.content).strip().startswith("PASS")
```

`monitor_node` 内对 `status=="completed"` 的任务调 review_node；不通过则：

- `retry_count < 3`：标 `ready` 重试（进 replan，复用现有 `_MAX_RETRIES` 机制，把 `_MAX_RETRIES` 调到 3）
- `retry_count >= 3`：标 `failed`，`error` 记录「审查 3 次未通过：<最后一次 FAIL 原因>」

**注意**：`_MAX_RETRIES` 现在=2，改为 3 以匹配用户决策；同时区分「执行失败重试」与「审查不通过重试」两种计数。

### 4.5 远端垂类 agent 注册机制

参考现有 `registry_center` 的 group 协作模式，为垂类 agent 增加 REST 类型注册：

- **开放注册接口**：registry_center 新增 `POST /api/external-agents`（名称、能力、base_url、认证类型），或复用 peers 表加 `agent_kind` 字段。
- **拉取**：PT 启动时（或动态刷新，同 `_refresh_approved` 模式）拉取已注册的垂类 agent，逐个 `RetrievalAdapter.connect()`，成功则注册进 `AgentRegistry`。
- **配置**：`.env` 增加 `PTA_EXTERNAL_AGENTS` 或从 registry_center 拉。

---

## 5. 改动清单

| 文件 | 改动 |
|------|------|
| `src/task_orchestrator/adapters/retrieval_adapter.py` | **新增** REST 检索适配器（submit→task_id，status/result 轮询） |
| `src/task_orchestrator/adapters/base.py` | 增加 `name` / `capabilities` 抽象属性 |
| `src/task_orchestrator/registry.py` | 增加 `get_by_capability()`；注册时带上 capabilities |
| `src/task_orchestrator/main_agent/exec_nodes.py` | `_MAX_RETRIES=3`；monitor 循环加 review 步骤；区分执行失败/审查不通过 |
| `src/task_orchestrator/main_agent/nodes.py` | plan 输出 agent_type 改为 capability 名；plan prompt 动态列出能力 |
| `src/task_orchestrator/main_agent/prompts.py` | PLAN_PROMPT 改能力枚举（retrieve/code/doc）；新增 REVIEW_PROMPT |
| `src/task_orchestrator/api/server.py` | build_registry 注册 RetrievalAdapter（从 registry_center 或配置拉取） |
| `src/task_orchestrator/registry_center/app.py` | 增加垂类 agent 注册/拉取端点 |
| `.env.example` | `PTA_EXTERNAL_AGENTS` / 认证配置 |
| `tests/` | 新增 RetrievalAdapter 测试（mock HTTP）、review 节点测试、3 次重试测试 |

---

## 6. 里程碑与验收

### M1：RetrievalAdapter（REST 异步任务）
- [ ] `submit` → `POST /tasks` 拿 task_id；`status`/`result` 轮询远端
- [ ] 认证头注入（Bearer / X-API-Key）
- [ ] mock HTTP 测试（httpx MockTransport）

### M2：能力路由层
- [ ] `base.py` 增 `name`/`capabilities`；`registry.get_by_capability()`
- [ ] plan prompt 从「三选一」改为「按能力选人」

### M3：每子任务独立审查
- [ ] `review_node`：LLM 对比要求 vs 结果 → PASS/FAIL
- [ ] monitor 循环接入；3 次未通过记录原因
- [ ] FakeLLM 测试：通过/不通过/重试超限

### M4：coding agent 注册
- [ ] 确认现有 CodexAdapter 覆盖 Claude Code/Codex；如接 Claude Code CLI 写 `ClaudeCodeAdapter`
- [ ] 远端 coding agent 走 A2AAdapter（复用，无新代码）

### M5：垂类 agent 注册接口（开放生态）
- [ ] registry_center 增 REST 类型注册/拉取
- [ ] PT 启动拉取并 connect 注册
- [ ] 集成测试：mock 一个远端 REST 检索 agent → 组员图走检索→审查→汇总

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 检索 agent 无标准 REST 约定 | 规划书固定 `POST /tasks` + `GET /tasks/{id}[/result]` 为规范，第三方按其实现 |
| 审查「完成度」歧义 | 固定 3 次重试，3 次未过记录「审查不通过原因」并标失败，不无限重试 |
| 本机 agent 误走 A2A | 判定标准按「部署位置」：同机→A2A，公网→REST；图侧按 capability 选人 |
| 远端不可达/慢 | `connect` 探测 + 超时；`status` 轮询带超时与最大次数 |
| 审查额外 LLM 调用增加成本 | review 只在 adapter 报 completed 后触发；FakeLLM 可测；真实 LLM 仅演示 |

---

## 8. 完成定义

- 全部现有测试（63）保持通过
- 新增测试全绿：RetrievalAdapter（mock HTTP）、review 节点、3 次重试、能力路由
- 一个真实场景走通：用户发布含检索+编码+文档的任务 → 子任务各自执行 → 每完成一个独立审查 → 汇总到任务栏标记完成
