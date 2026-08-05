# 审计文档：当前设计对"多 Agent 复杂任务编排系统"的可行性评估

> 依据：当前 `PersonalTaskAgent` 源码审计 + 开源社区 6 类真实案例调研（opencode、Codex CLI、A2A Protocol、LangGraph/DeepAgents、CrewAI、Agno）
> 日期：2026-08-01

---

## 1. 目标架构简述

用户期望的系统：

```
用户 ←→ Main Agent（任务规划 + 分解 + 分配）
           │
           ├── A2A ──→ 云端 Agent（HuanLink 等，公网可达）
           ├── 本地协议 ──→ 本地 Coding Agent（Codex CLI、opencode）
           └── 本地协议 ──→ 本地基础 Agent（email、shell、文件操作）
```

核心能力：
- **任务规划**：将用户的复杂请求分解为可执行的子任务序列
- **任务分发**：将子任务分配给合适的 SubAgent（支持并行）
- **SubAgent 异构**：云端 Agent（A2A）、本地代码 Agent（Codex/opencode）、本地工具 Agent
- **异步执行与状态追踪**：长任务不阻塞用户交互
- **结果聚合**：子任务结果汇总后生成最终回复

---

## 2. 当前架构审计

### 2.1 A2A 版本：0.3 — 与真实世界断裂

| 项目 | A2A 版本 | Wire Format | 能否互联 |
|------|---------|-------------|----------|
| PersonalTaskAgent (本项目) | **0.3.26** | JSON-RPC | — |
| HuanLink | **1.0** | Protobuf | ❌ |
| Codex CLI | 自定义 JSON-RPC | JSON | ❌ (非 A2A) |
| opencode | 无网络 API | — | ❌ |
| A2A Protocol 生态 | **1.0** | Protobuf | ❌ |

**结论：A2A 0.3 是孤立生态。** 互联网上所有公开 A2A Agent（包括 HuanLink）均使用 1.0。0.3 的 `a2a-sdk` 已停更，1.0 是 Google 用 protobuf 全量重写。当前项目无法与任何外部 Agent 通信，连 HuanLink 都不行。

**处理方案：必须升级到 `a2a-sdk >= 1.0` 或引入独立的协议转换层。**

### 2.2 任务规划：不存在

当前 Host（`graph.py:18-35`）的核心逻辑：

```python
# 系统提示词片段
"涉及待办任务/提醒/备忘的请求,按工具描述选择对应远端;一次只处理用户的当前诉求"
```

这是**单步路由**，不是**任务规划**。用户说"帮我整理这周的工作然后发邮件给老板"，当前系统做不到：

1. **无分解能力**：没有 planner 节点将复杂任务拆成子步骤
2. **无依赖编排**：无法表达"先查任务列表 → 再生成周报 → 最后发邮件"
3. **无并行调度**：无法同时调多个 Agent
4. **无状态追踪**：不知道哪个子任务完成了、哪个失败了

对比真实案例：

| 系统 | 规划方式 |
|------|----------|
| CrewAI | Hierarchical: Manager LLM auto-delegates, tasks have `context` 传递依赖 |
| LangGraph | 显式 StateGraph: planner node → executor nodes → aggregator node |
| OpenAI Agents SDK | Handoffs + agents as tools: 链式传递控制权 |
| DeepAgents | Planning + sub-agents + filesystem state |

**处理方案：Host 需要从"单步路由 ReAct"升级为"规划-执行-聚合"三段式。**

### 2.3 Agent 发现机制：AgentCard 假设不成立

当前设计的核心假设（`remote_tools.py:72-101`）：
> 每个远端 Agent 都提供 `/.well-known/agent-card.json`，Host 通过它发现能力

**现实：**
- **opencode**：纯 CLI 工具，无 HTTP 端点，无 AgentCard。它是被用户键盘驱动的，不是被外部系统调用的。
- **Codex**：有 Python SDK (`openai-codex`) 和自定义 JSON-RPC app-server，但**不提供 AgentCard**。
- **HuanLink**：提供 A2A 1.0 AgentCard，但在公网。

**处理方案：需要多套 Agent 接入适配器，不能只依赖 AgentCard 一种发现机制。**

### 2.4 SubAgent 生命周期：不支持

当前架构的一个 Agent 调用 = Host 发一条 A2A Message → 等一个终态结果：

```python
# client.py:110-156
async def send(self, text, context_id=None, task_id=None):
    result = await self._send_once(...)  # 阻塞等终态
    return result
```

**缺失的能力：**
- **异步启动**：启动长期任务后立即返回受理回执，不阻塞
- **状态查询**：查询某个子任务的中间状态
- **取消/暂停**：终止或暂停正在执行的子任务
- **子任务链**：一个子任务完成后自动触发下一个
- **并行执行**：多个子任务同时进行

HuanLink 的 `executionMode: async | blocking`（§3.2）正是为了补这个缺口。

**处理方案：需要引入任务队列 + 异步执行模式 + 终态回调机制。**

### 2.5 本地工具 Agent：不存在

当前三个 Agent 是任务/提醒/备忘，没有：
- Shell 命令执行
- 电子邮件收发
- 文件系统操作（非数据库）
- 浏览器操作
- Git 操作

**对比真实案例：**
- DeepAgents：内置 filesystem + shell + MCP 工具
- Codex/opencode：就是全功能的 coding agent（shell + 文件 + git）
- Agno: 100+ 工具集成

**处理方案：需要一个新的"本地执行 Agent"，可以自己实现，也可以桥接到 Codex/opencode。**

### 2.6 架构耦合：monorepo 不适用于异构 Agent

当前所有 Agent 共享 `common/` 和 `a2a_infra/`：
```
src/personal_task_agent/
├── common/          ← TaskManager、Reminder、Memo 都依赖
├── a2a_infra/       ← 同上
└── agents/          ← 都 import common 和 a2a_infra
```

如果 SubAgent 是 Go 写的 Codex 或 TypeScript 写的 opencode，这条依赖链瞬间断裂。异构 Agent 不能共享 Python 代码库。

**处理方案：每个 SubAgent 需要独立的适配器层（如 HuanLink 的 `codex-a2a-adapter`），Main Agent 只通过协议接口与它们交互。**

---

## 3. 现有模块评估：哪些可保留

| 模块 | 评估 | 理由 |
|------|------|------|
| `common/config.py` | ✅ 可复用 | pydantic-settings 配置模式是干净的，需要扩展新的配置项 |
| `common/db.py` | ✅ 可复用 | 数据库抽象层和 Repository 模式 |
| `common/log.py` | ✅ 可复用 | JSON/Console 日志 + contextvars 上下文贯穿 |
| `common/llm.py` | ✅ 可复用 | FakeLLM 工厂模式 + ScriptedChatModel |
| `common/agent_loop.py` | ✅ 可复用 | 30 行手写 ReAct 循环，独立且无外部依赖 |
| `a2a_infra/` | ⚠️ 需升级 | A2A 0.3 → 1.0 大版本迁移，API 面全变 |
| `a2a_infra/server.py` | ⚠️ 需重写 | `A2AStarletteApplication` API 在 1.0 完全改变 |
| `a2a_infra/client.py` | ⚠️ 需重写 | 1.0 的 `ClientFactory`/`send_message` 签名变化 |
| `a2a_infra/executor.py` | ⚠️ 需重写 | 1.0 的 `AgentExecutor`/`TaskUpdater` 基类变化 |
| `agents/task_manager/` | ❌ 废弃 | 业务领域不匹配新目标，但工具/仓储模式可参考 |
| `agents/reminder/` | ❌ 废弃 | 同上。规则引擎模式（无 LLM 的 executor）思路可保留 |
| `agents/memo/` | ❌ 废弃 | FTS5 中文检索方案可复用 |
| `host/graph.py` | ❌ 需重写 | 从"单步路由 ReAct"升级为"规划-执行-聚合" |
| `host/remote_tools.py` | ⚠️ 可参考 | AgentCard→Tool 转译思路可复用，但需要支持多协议 |
| `host/cli.py` | ✅ 可参考 | REPL 交互、会话管理、流式输出 |
| `tests/` 体系 | ✅ 可复用 | FakeLLM、临时 DB fixture、集成测试起真实服务模式 |

---

## 4. 关键矛盾清单

### 矛盾 1：A2A 0.3 vs A2A 1.0

**问题**：项目使用的协议版本与整个生态（包括 HuanLink）不兼容。

**解决方向**：
- A：直接升级到 `a2a-sdk >= 1.0`（工作量大，protobuf 全量重写）
- B：保留 0.3 作为 A2A 概念原型，新项目从头用 1.0
- **建议 B**：既然要做推到重来，直接上 1.0，避免两个版本同时维护

### 矛盾 2：AgentCard 假设 vs 真实 Agent 异构性

**问题**：opencode 无 HTTP API、Codex 无 AgentCard、HuanLink 有 AgentCard 但用 A2A 1.0。不能假设所有 Agent 都按同一种方式被发现和调用。

**解决方向**：引入 **Agent Adapter 层**（参考 HuanLink 的 `codex-a2a-adapter`）：
```
Main Agent
  ├─ A2A Client (for A2A-compatible agents)
  ├─ Codex Adapter (wraps openai-codex SDK)
  ├─ opencode Adapter (wraps opencode CLI/tool calling)
  └─ Local Agent (in-process, for simple tools)
```
每个 Adapter 负责将 Main Agent 的任务翻译为对应 Agent 的协议。

### 矛盾 3：单步调用 vs 异步任务编排

**问题**：当前 `client.send()` 是同步阻塞等终态。复杂任务需要异步提交 + 中间状态查询 + 结果回调。

**解决方向**：
- HuanLink 的 `executionMode: async/blocking` 模式值得借鉴
- 需要统一任务生命周期管理（`submitted → working → completed/failed/input-required`）
- A2A 1.0 的 Task 状态机可以直接复用

### 矛盾 4：opencode 不能被外部系统调用

**问题**：opencode 是 CLI 工具，没有网络 API。它不能作为一个"远端 Agent"被其他系统通过 HTTP/RPC 调用来执行任务。

**解决方向**：
- **方案 A**：用 opencode 的 headless 模式（如果支持）或通过 stdin/stdout 协议驱动
- **方案 B**：放弃直接调用 opencode，改用 Codex Python SDK（有正式可编程接口）
- **方案 C**：自己实现一个本地 shell/coding agent（类似 DeepAgents 的模式）
- **建议**：优先用 Codex SDK 作为本地 coding agent（有 103k star 的成熟度），opencode 作为备选或手动切换的选项

### 矛盾 5：HuanLink 的角色定位

**问题**：HuanLink 本身就是 MainAgent+Codex 的编排层。如果新项目也做 MainAgent，HuanLink 变成 SubAgent 还是竞品？

**解决方向**：
- HuanLink 已有 A2A 1.0 AgentCard，如果你的新 Main Agent 也支持 A2A 1.0，可以直接把它作为一个"云端代码执行服务"来调用
- 但注意 HuanLink 的 MainAgent 角色与新项目重叠——**让两个 MainAgent 互调会造成无限循环**

**建议**：只在需要远程代码执行时调用 HuanLink 背后的 Codex 链条，不把 HuanLink 当 SubAgent。或者直接绕过 HuanLink，新项目自己接入 Codex SDK。

---

## 5. 建议的项目形态与技术选型

### 5.1 架构建议

```
┌─────────────────────────────────────────────────┐
│  Main Agent (任务规划 + 分解 + 状态追踪)         │
│  · LangGraph 显式 StateGraph                    │
│  · Planner → Dispatcher → Monitor → Aggregator  │
│  · SQLite checkpointer (多轮记忆)               │
└──┬──────────────────┬──────────────┬────────────┘
   │                  │              │
   ▼ A2A 1.0         ▼ Python SDK   ▼ 进程内
┌───────────┐  ┌───────────┐  ┌──────────────┐
│ A2A Adapter│  │ Codex     │  │ Local Agent  │
│ (HuanLink │  │ Adapter   │  │ · shell      │
│  等云Agent)│  │ (Codex SDK│  │ · email      │
│           │  │  接入)    │  │ · file/git   │
└───────────┘  └───────────┘  │ · web search │
                              └──────────────┘
```

### 5.2 技术选型建议

| 层次 | 建议 | 理由 |
|------|------|------|
| Main Agent 框架 | **LangGraph** (显式 StateGraph) | 需要规划节点、分配节点、聚合节点，不是简单的单步路由，`create_react_agent` 不够用 |
| Agent 间通信 | **A2A 1.0** (a2a-sdk >= 1.0) | 互联网上的 Agent 都在 1.0，必须跟上 |
| 本地 Coding Agent | **Codex Python SDK** | 成熟度最高（103k star），有正式 API，Python 集成最方便 |
| 本地工具 Agent | **自建**（LangGraph + MCP 工具） | Shell/email/file 这些工具生态成熟，自建量不大 |
| 配置管理 | **pydantic-settings** | 已有验证，保持 |
| 持久化 | **SQLite + WAL** | 单用户场景保持轻量 |
| 语言 | **Python 3.12+** | Main Agent 的框架生态在 Python |

### 5.3 opencode 的定位

opencode 作为**用户交互入口**而不是被调用的 SubAgent。用户通过 opencode 与新系统对话（就像现在这样），Main Agent 在背后规划并分发任务。这是 opencode 在当前架构下最自然的角色。

---

## 6. 待确认的开放问题

1. **HuanLink 的 A2A 1.0 AgentCard URL**是什么？需要确认其公网可达性和 AgentCard 结构。
2. **Codex SDK 的本地安装方式**：`pip install openai-codex` 后是否需要登录？沙箱配置需求？
3. **Email Agent 的实现深度**：只需要 Gmail SMTP/IMAP 还是需要 Exchange/Outlook？是否需要 OAuth？
4. **任务规划的策略**：Plan-then-execute（一次性规划完再执行）还是 Replan（每步执行后重新规划）？
5. **是否保留人机协同**：复杂任务的关键步骤是否需要用户确认再继续（类似 opencode 的 permission 机制）？
