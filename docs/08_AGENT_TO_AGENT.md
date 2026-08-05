# 实现规划书：Agent 间任务下发与角色权限模型（v2 对 v2）

> 状态：规划阶段
> 前置文档：[06_PLAN_v2.md](06_PLAN_v2.md)（v2 总规划）、[AUDIT.md](AUDIT.md)
> 日期：2026-08-04

---

## 1. 目标

### 1.1 一句话定义

让 **v2 Main Agent** 既能作为**下发方**（组长 PT）把子任务通过 A2A 1.0 分派给另一个 v2 Main Agent（组员 PT），又能作为**被调用方**（组员 PT）接收任务后自己再规划执行；并按角色划分权限，限制组员只能通过邮箱向组长传递报告书。

### 1.2 团队场景（用户原始设想）

```
组长 PT (:8100, role=leader)
  ├─ 读任务规划书(人类提供)
  ├─ A2A 下发 → 组员 PT 执行子任务
  └─ email_read 整理组员报告书 → 生成具体日程(决策由组长本人做)

组员 PT (:8101, role=member, A2A 服务端)
  ├─ 接收组长下发的子任务 → 自己再规划
  │    例: "10-11点开会" → 设置提醒子任务
  │         "15-16点开发" → 发布开发规划到本地 coding agent
  └─ email_send 把任务报告书发回组长邮箱
```

### 1.3 权限模型（验收核心）

| 角色 | 拥有权限 | 明确禁止 |
|------|----------|----------|
| 组长 `leader` | A2A 向组员下发；email_read 读组员报告 | 不直接执行具体任务 |
| 组员 `member` | 执行下发任务；email_send 发报告书 | **禁止向任何 agent 下发任务** |

权限靠**双层**保障：
1. **结构层**（硬）：组员 role 的 `AgentRegistry` 不注册 A2AAdapter → 图无法调用远端下发
2. **提示词层**（软）：规划器 prompt 注入能力边界，让 LLM 不做越权规划

---

## 2. 现状审计

| 能力 | 现状 | 缺口 |
|------|------|------|
| A2A 1.0 客户端 | ✅ `a2a_client.py` 完整 | — |
| A2A 1.0 服务端装配 | ✅ `a2a_server.py` `build_a2a_app` | — |
| LangGraph→A2A 执行器 | ✅ `a2a_executor.py` `LangGraphAgentExecutor` | — |
| A2A 服务端 CLI 入口 | ❌ `cli/` 为空 | 需写 `__main__.py` |
| 邮件工具 | ❌ tools.py 只有 shell/file/web | 需写 email_send/email_read |
| 角色/权限配置 | ❌ config 无 role | 需加 `a2a_role` 等 |

---

## 3. 技术设计

### 3.1 拓扑

```
组长 PT                               组员 PT
┌─────────────────────────┐          ┌──────────────────────────┐
│ Main Agent (role=leader)│          │ Main Agent (role=member) │
│ registry:               │          │ registry:                │
│  ├─ A2AAdapter →:8101   │──A2A────▶│  ├─ Local(shell/file/    │
│  ├─ Local(含 email_read)│  下发任务  │  │     web/email_send)   │
│  └─ Codex(Mock)         │          │  └─ Codex(Mock)          │
│ CLI / Web API (:8000)   │          │ A2A 服务端 (:8101)       │
└─────────────────────────┘          └──────────────────────────┘
        │  email_read                     │  email_send
        ▼                                 ▼
    组长邮箱 ◄───────── 任务报告书 ──────────┘
```

### 3.2 角色配置

```python
# common/config.py 新增
a2a_role: Literal["leader", "member"] = "member"   # 组长可下发;组员只被下发
a2a_port: int = 8101                               # 组员 A2A 服务端监听端口
a2a_agent_name: str = "Team Member PT"             # AgentCard 名称
a2a_agent_description: str = "..."                 # AgentCard 能力描述(供组长 LLM 规划)
```

### 3.3 A2A 服务端入口（`cli/__main__.py`）

```python
def main():
    settings = get_settings()
    model = build_chat_model()
    registry = build_registry(model, role=settings.a2a_role)
    graph = build_main_agent(model, registry)
    executor = LangGraphAgentExecutor(graph, settings.a2a_agent_name)
    card = build_agent_card(name=..., description=..., url=..., skills=[...])
    app = build_a2a_app(card, executor, api_key=settings.a2a_api_key)
    run_agent(app, settings.bind_host, settings.a2a_port)
```

组员 PT 收到子任务文本 → `LangGraphAgentExecutor.execute` → `graph.ainvoke` → 组员 Main Agent 自己走 understand→plan→dispatch→aggregate → 返回 final_response 作为 A2A artifact。

### 3.4 角色注入图（权限软约束）

`build_main_agent` 根据 role 注入不同 agents_info 到 `plan_node`：
- `member`：提示词明确"你无权向其他 Agent 下发任务，只能执行本地任务，并通过 email_send 向组长发送任务报告书"
- `leader`：提示词包含 A2A 可下发能力 + email_read 收集工具

### 3.5 邮件工具

```python
# local_agent/tools.py 新增
@tool
async def email_send(to: str, subject: str, body: str) -> str:  # SMTP
@tool
async def email_read(folder: str = "INBOX", limit: int = 10) -> str:  # IMAP
```

- 读 `settings.smtp_host` 等；未配置时返回清晰错误（CI 安全）
- 加到 `build_local_agent` 的 available，按 `PTA_LOCAL_TOOLS` 启用

### 3.6 `build_registry` 增加 role 参数

```python
def build_registry(model=None, role: str = "leader") -> AgentRegistry:
    ...
    if role == "leader":
        for agent_cfg in settings.a2a_agents:
            registry.register(A2AAdapter(...))   # 仅组长有下发能力
    ...
```

---

## 4. 改动清单

| 文件 | 改动 |
|------|------|
| `src/task_orchestrator/cli/__main__.py` | **新增** A2A 服务端入口 |
| `src/task_orchestrator/common/config.py` | 加 `a2a_role`/`a2a_port`/`a2a_agent_name`/`a2a_agent_description` |
| `src/task_orchestrator/local_agent/tools.py` | 加 `email_send`/`email_read` |
| `src/task_orchestrator/api/server.py` | `build_registry` 加 role 参数 |
| `src/task_orchestrator/main_agent/graph.py` | role 注入 agents_info |
| `src/task_orchestrator/main_agent/prompts.py` | 组长/组员能力提示词 |
| `tests/integration/test_agent_to_agent.py` | **新增** A2A 下发集成测试 |
| `.env.example` | 双角色配置示例 |

---

## 5. 里程碑与验收

### M1：邮件工具（mock SMTP 可测）
- [ ] `email_send` SMTP 实现 + mock SMTP 测试
- [ ] `email_read` IMAP 实现 + 无配置报错测试

### M2：A2A 服务端入口 + 角色配置
- [ ] `cli/__main__.py` 能把 Main Agent 图包成 A2A 服务端
- [ ] `config` 角色配置
- [ ] 启动后 `/.well-known/agent-card.json` 可发现

### M3：权限模型
- [ ] `build_registry` role 参数：member 无 A2AAdapter
- [ ] prompt 角色注入：member 禁下发，leader 含下发+收集

### M4：集成测试（核心验收）
- [ ] 起组员 A2A 服务端（脚本化图）
- [ ] 组长侧 `A2AAdapter` connect→submit→poll→断言组员结果
- [ ] 断言组员 registry 无 A2AAdapter（结构上无下发）

### M5：真实双实例演示（可选，需 SMTP）
- [ ] 组员 PT `python -m task_orchestrator.cli`（member）
- [ ] 组长 PT 发"给组员下发明天3点提醒" → 组员规划设置提醒
- [ ] 组员 email_send 报告书 → 组长 email_read 整理

---

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 组员收到任务后自己规划，可能再调别的 A2A 造成嵌套 | member role 结构上无 A2AAdapter，物理杜绝 |
| 真实邮箱 SMTP/IMAP 未配置 | 工具实现 + mock SMTP 测试，无配置返回明确错误 |
| A2A 1.0 服务端 API 与文档不一致 | 复用已通过的 `test_a2a_v1.py` 集成测试模式 |
| 组长下发被组员误当普通对话 | executor 收到即跑组员图，图本身有规划能力，天然适配 |

---

## 7. 完成定义

- 全部现有测试（57）保持通过
- 新增 `test_agent_to_agent.py` 通过：一个 v2 PT 通过 A2A 对另一个 v2 PT 下发任务并拿到结果
- 组员 role 无 A2AAdapter（代码可断言）
