# 项目规划书：多 Agent 复杂任务编排系统 v2.0

> 状态：规划阶段
> 前置文档：[AUDIT.md](AUDIT.md)（审计结论）
> 日期：2026-08-01

---

## 1. 项目定位

### 1.1 一句话定义

一个**个人复杂任务处理 Agent**：Main Agent 理解用户意图后自动进行任务规划与分解，将子任务分配给不同类型的 SubAgent（云端 A2A Agent、本地 Codex 代码 Agent、本地工具 Agent）并行或串行执行，最终聚合结果返回给用户。

### 1.2 与 v1.0 的本质区别

| | v1.0 (PersonalTaskAgent) | v2.0 (本规划) |
|---|---|---|
| 编排模式 | 单步路由（选一个工具调一次） | **规划-分解-分配-聚合** |
| SubAgent 来源 | 全部自建，monorepo 内 | 自建 + **接入外部 Agent** |
| SubAgent 类型 | 同构（全 Python） | **异构**（A2A/Codex SDK/进程内） |
| A2A 版本 | 0.3（孤立生态） | **1.0**（与互联网互联） |
| 用户场景 | 任务/提醒/备忘 CRUD | 任何可分解的个人复杂事务 |

### 1.3 成功标准（验收清单）

| # | 验收项 | 验证方式 |
|---|--------|----------|
| V1 | Main Agent 将"整理本周工作并准备周报"分解为 ≥2 个子任务 | 手工演示 + E2E 测试 |
| V2 | 一个子任务分配给 Codex 执行代码操作，一个分配给本地工具 Agent 发邮件 | 集成测试 + 手工演示 |
| V3 | 子任务失败时系统自动重规划或向用户请求决策 | 集成测试（故意让子任务失败） |
| V4 | 与一个外部 A2A 1.0 Agent 完成一次委托调用 | 集成测试 |
| V5 | 全量测试在无任何外部 API key 的环境下通过（FakeLLM + Mock Codex） | CI |
| V6 | `docker compose up` 一键启动全部服务 | 手工验证 |

---

## 2. 架构设计

### 2.1 拓扑

```
┌──────────────────────────────────────────────────┐
│  Main Agent                                      │
│  LangGraph 显式 StateGraph                       │
│  nodes: understand → plan → dispatch → aggregate │
│  state: tasks[], results[], agent_registry       │
│  checkpointer: SQLite (多轮记忆)                  │
└───┬──────────────┬───────────────┬───────────────┘
    │              │               │
    ▼              ▼               ▼
┌────────┐  ┌───────────┐  ┌──────────────┐
│ A2A    │  │ Codex     │  │ Local        │
│ Adapter│  │ Adapter   │  │ Agent        │
│        │  │           │  │              │
│ 协议级  │  │ SDK 调用  │  │ 进程内工具     │
│ A2A 1.0│  │ Codex CLI │  │ shell/email  │
│ 云端Agent│ │ 本地代码   │  │ file/web/git │
└────────┘  └───────────┘  └──────────────┘
```

### 2.2 核心技术决策（已选定）

| 决策 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.12+ | LangGraph/Codex SDK 生态均是 Python |
| Agent 框架 | **LangGraph 显式 StateGraph** | 需要多个有条件分支的节点（规划/分发/聚合），不是简单的单步路由 |
| Agent 间协议 | **A2A 1.0** (a2a-sdk >= 1.0) | 互联网生态基准版本 |
| 本地代码执行 | **Codex Python SDK** (`openai-codex`) | 成熟度最高（103k star），有正式 Python API |
| 本地基础工具 | **自建**，进程内 LangChain 工具 | Shell/email/file 工具量不大，自己写更可控 |
| 持久化 | **SQLite WAL** | 单用户场景的正确尺寸 |
| 配置 | **pydantic-settings** | 已验证，从 v1.0 复用 |
| LLM 接入 | OpenAI 兼容接口 (`langchain-openai`) | 厂商无关，FakeLLM 可注入 |
| 测试 | FakeLLM + Mock Codex + 真实 A2A 服务 | 无需任何外部 key 全绿 |

### 2.3 不做的事情

- **不做** opencode 集成：opencode 无网络 API，方案成本过高。改用 Codex SDK。
- **不做** HuanLink 直接集成：角色重叠（它自己就是 MainAgent），改为直连 Codex SDK。
- **不做** Web 前端 / 多通道：入口仍为 CLI。
- **不做** 多用户 / 租户体系：单用户本地部署。
- **不做** Jieba 分词 / 向量检索：本项目重心在编排，不在检索。

---

## 3. 关键流程设计

### 3.1 整体流程

```
用户输入
  → [understand] LLM 理解意图
  → [plan] LLM 输出任务计划（JSON: tasks with agent_type, deps）
  → [dispatch] 遍历计划，对就绪任务选择适配器并提交
  → [monitor] 等待子任务完成（并行轮询）
  → [replan?] 有失败 → LLM 决定重试/跳过/询问用户
  → [aggregate] LLM 聚合并返回最终回复
```

### 3.2 LangGraph 节点设计

```
State 定义:
  messages: list[BaseMessage]    # 对话历史
  user_request: str              # 原始请求
  task_plan: list[SubTask]       # 计划中的子任务
  completed: dict[str, str]      # task_id → result
  final_response: str            # 最终回复

节点:
  START → understand_node
  understand_node → plan_node
  plan_node → dispatch_node
  dispatch_node → monitor_node
  monitor_node → replan_node  (有失败)
  monitor_node → aggregate_node  (全部完成)
  replan_node → dispatch_node  (重新分配)
  aggregate_node → END
```

### 3.3 SubTask 模型

```python
@dataclass
class SubTask:
    task_id: str              # 唯一 ID
    description: str          # 给执行 Agent 看的指令
    agent_type: str           # "a2a" | "codex" | "local"
    agent_target: str         # A2A url / Codex sandbox / local tool name
    dependencies: list[str]   # 依赖的 task_id 列表
    status: str               # pending/ready/running/completed/failed
    result: str | None
```

### 3.4 Plan 的 LLM 输出格式

```json
{
  "tasks": [
    {
      "task_id": "1",
      "description": "搜索最近一周的 git 提交记录并生成变更摘要",
      "agent_type": "codex",
      "agent_target": "workspace_write",
      "dependencies": []
    },
    {
      "task_id": "2",
      "description": "查找未完成的任务列表",
      "agent_type": "a2a",
      "agent_target": "http://localhost:10001",
      "dependencies": []
    },
    {
      "task_id": "3",
      "description": "基于 task 1 的代码变更和 task 2 的任务完成情况，写一封周报邮件发送给 manager@company.com",
      "agent_type": "local",
      "agent_target": "email_sender",
      "dependencies": ["1", "2"]
    }
  ]
}
```

### 3.5 子任务并行执行（关键设计点）

步骤 3 依赖 1 和 2 → dispatch_node 先提交 1 和 2（并行），monitor 等两者都完成后再提交 3。LangGraph 的 `monitor_node` 轮询所有 running 任务，当所有就绪任务的依赖都满足时，重新进入 `dispatch_node`。

---

## 4. Agent 适配器层设计

### 4.1 统一接口

```python
class BaseAdapter(ABC):
    """所有 SubAgent 适配器的统一接口。"""

    @abstractmethod
    async def submit(self, task: SubTask) -> str:
        """提交任务，返回外部 task_id（用于查询/取消）。"""

    @abstractmethod
    async def status(self, external_id: str) -> str:
        """查询任务状态: pending/running/completed/failed。"""

    @abstractmethod
    async def result(self, external_id: str) -> str | None:
        """获取任务结果（终态后调用）。"""

    @abstractmethod
    async def cancel(self, external_id: str) -> bool:
        """取消任务。"""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """返回适配器类型标识。"""
```

### 4.2 A2A Adapter

- 基于 `a2a-sdk >= 1.0` 的 `create_client()` 和 `A2ACardResolver`
- 启动时发现远程 AgentCard，注册到 agent_registry
- 支持 `streaming=True` 获取中间状态
- 利用 A2A 1.0 原生的 Task 状态机

### 4.3 Codex Adapter

- 基于 `openai-codex` Python SDK
- 封装 `Codex.thread_start(sandbox=...)` 和 `thread.run()`
- 每个子任务对应一个 Codex thread
- 本地文件系统访问通过 Codex 的 sandbox 机制控制
- **Mock 策略**：测试中用一个返回固定文本的假 Codex 实例替换

### 4.4 Local Adapter

- 进程内 Agent，无网络通信开销
- 通过 LangChain `@tool` 定义工具集：
  - `shell_exec`：执行命令（需确认确认）
  - `email_send`：SMTP 发邮件
  - `email_read`：IMAP 读邮件
  - `file_read / file_write`：文件操作
  - `web_fetch`：HTTP 请求
  - `git_log / git_diff`：Git 操作
- 内部用 `agent_loop.py` 的手写 ReAct 循环（从 v1.0 复用）

---

## 5. Agent 注册机制

### 5.1 设计原则

放弃 v1.0 "假设所有 Agent 都暴露 AgentCard" 的设计，改为**显式配置 + 动态发现**混合模式：

- **A2A Agent**：通过 AgentCard 动态发现（配置里只写 URL）
- **Codex Agent**：显式配置（sandbox、model、workspace）
- **Local Agent**：编译期注册（就是代码的一部分）

### 5.2 配置结构

```python
class AgentRegistry:
    a2a_agents: list[A2AAgentConfig]   # [{name, url, api_key}]
    codex_agent: CodexAgentConfig      # {sandbox, model}
    local_tools: list[str]             # ["shell", "email", "file", "web", "git"]
```

配置示例（`.env`）：

```env
# A2A 远端 Agent 列表（逗号分隔的 URL）
PTA_A2A_AGENTS=http://huanlink.example.com,http://other-agent.example.com
PTA_A2A_API_KEY=sk-xxx

# Codex 配置
PTA_CODEX_ENABLED=true
PTA_CODEX_SANDBOX=workspace_write
PTA_CODEX_MODEL=gpt-5.4

# 本地工具
PTA_LOCAL_TOOLS=shell,email,file,web
```

---

## 6. 目录结构

```
project/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── docker-compose.yml
├── docker/
│   └── Dockerfile
├── docs/
│   ├── 01_PLAN.md
│   ├── 02_ARCHITECTURE.md
│   ├── 03_CODE_GUIDE.md
│   └── 04_RUNBOOK.md
├── src/task_orchestrator/
│   ├── __init__.py
│   ├── common/                    # 从 v1.0 复用（裁剪）
│   │   ├── config.py              # pydantic-settings
│   │   ├── db.py                  # SQLite 抽象
│   │   ├── llm.py                 # LLM 工厂 + FakeLLM
│   │   ├── log.py                 # 日志
│   │   └── agent_loop.py          # 手写 ReAct 循环
│   ├── main_agent/                # Main Agent 核心
│   │   ├── __init__.py
│   │   ├── graph.py               # StateGraph 定义
│   │   ├── nodes.py               # understand/plan/dispatch/monitor/replan/aggregate
│   │   ├── state.py               # GraphState 定义
│   │   └── prompts.py             # 系统提示词模板
│   ├── adapters/                  # Agent 适配器
│   │   ├── __init__.py
│   │   ├── base.py                # BaseAdapter 接口
│   │   ├── a2a_adapter.py         # A2A 1.0 适配器
│   │   ├── codex_adapter.py       # Codex SDK 适配器
│   │   └── local_adapter.py       # 本地工具适配器
│   ├── local_agent/               # 本地工具 Agent
│   │   ├── __init__.py
│   │   ├── agent.py               # build_local_agent()
│   │   ├── tools.py               # shell/email/file/web/git 工具
│   │   └── executor.py            # LocalExecutor
│   ├── registry.py                # AgentRegistry（配置 + 动态发现）
│   └── cli/
│       ├── __init__.py
│       ├── __main__.py            # 入口
│       └── repl.py                # REPL 交互
└── tests/
    ├── conftest.py                # FakeLLM + MockCodex + 临时库
    ├── unit/
    │   ├── test_nodes.py          # 各节点逻辑
    │   ├── test_adapters.py       # 适配器接口
    │   ├── test_registry.py       # 注册机制
    │   ├── test_local_tools.py    # 本地工具
    │   └── test_graph.py          # StateGraph 行为
    └── integration/
        ├── conftest.py            # 起真实服务
        ├── test_plan_execute.py   # 完整规划-执行流
        ├── test_a2a_adapter.py    # A2A 适配器集成测试
        └── test_parallel_tasks.py # 并行子任务测试
```

---

## 7. 里程碑

### M1：骨架 + common 层 + A2A 1.0 验证（2-3 天）

**内容**：
- `pyproject.toml` 与依赖锁定（a2a-sdk>=1.0, langgraph, langchain-openai, openai-codex）
- 从 v1.0 复用 `common/`（config/db/llm/log/agent_loop），裁剪不需要的部分
- 验证 a2a-sdk 1.0 的 API（服务端组装、客户端调用、AgentCard 数据结构）
- 编写 A2A 1.0 的最小验证服务与客户端测试

**完成定义**：`pytest` 中 A2A 1.0 客户端能发现 AgentCard、调用 `message/stream`、正确消费 Task 状态变化。

### M2：Main Agent 规划图（3-4 天）

**内容**：
- 定义 `GraphState` 和 `SubTask` 数据模型
- 实现 `understand_node`、`plan_node`、`aggregate_node`
- 实现 plan 的 LLM prompt（输出结构化 JSON 任务列表）
- 单元测试：Mock LLM 输入一句话，验证能产出合法的 task_plan JSON
- 集成测试：FakeLLM 驱动完整 plan→aggregate 流程

**完成定义**：给定"整理本周工作和准备周报"类输入，plan_node 能输出含依赖关系的子任务列表。

### M3：适配器层（3-4 天）

**内容**：
- 实现 `BaseAdapter` 接口
- **A2AAdapter**：启动时发现 AgentCard → 注册，运行时 `submit/status/result`
- **CodexAdapter**：封装 Codex SDK，测试中提供 `MockCodexAdapter`
- **LocalAdapter**：进程内适配器，直接调本地工具
- `AgentRegistry` 管理所有适配器实例

**完成定义**：三种适配器各有单元测试，Mock 模式下能完成 "submit → poll → get_result" 完整生命周期。

### M4：本地工具 Agent（2-3 天）

**内容**：
- 实现本地工具：
  - `shell_exec(command)` — 可配置黑名单（如禁止 `rm -rf`）
  - `email_send(to, subject, body)` — SMTP
  - `file_read(path) / file_write(path, content)` — 文件操作
  - `web_fetch(url)` — HTTP GET
- `build_local_agent()` 用 `agent_loop.py` 组装
- 工具内部用 pydantic 校验参数

**完成定义**：本地 Agent 能通过 ReAct 循环自主组合这些工具完成任务（如"查天气并保存到文件"）。

### M5：dispatch + monitor + replan 节点（3-4 天）

**内容**：
- `dispatch_node`：遍历 task_plan，对就绪任务通过相应适配器提交
- `monitor_node`：轮询所有 running 任务，收集完成/失败状态
- `replan_node`：子任务失败时，LLM 决策是重试/替换 agent/跳过/询问用户
- 依赖解析：只有依赖全部完成的任务才进入 ready 状态
- 并行执行：多个无依赖的子任务同时提交

**完成定义**：端到端测试通过——2 个并行子任务 + 1 个依赖子任务，失败子任务触发重规划。

### M6：CLI + Docker + 文档（2 天）

**内容**：
- CLI REPL（从 v1.0 复用模式）：`/help` `/agents` `/tasks` `/exit`
- 流式输出（显示子任务提交/完成/失败状态）
- Docker 化
- README + 快速开始

**完成定义**：验收清单 V1-V6 全部通过。

---

## 8. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| a2a-sdk 1.0 API 与文档不一致 | 中 | M1 首项工作就是真实 API 校验（吸取 v1.0 教训） |
| Codex SDK 认证流程复杂 | 中 | 提供 Mock 适配器，无 Codex 也可体验全链路；CI 只用 Mock |
| LLM 规划质量不稳定 | 高 | 测试固化为 FakeLLM 的确定性输出；prompt 持续迭代 |
| 并行子任务的状态同步竞争 | 低 | LangGraph 的 StateGraph 是单步执行的，天然线程安全 |
| 本地工具的邮箱配置（SMTP/IMAP） | 低 | 提供 .env 配置模板；CI 中用 mock SMTP |
| 依赖解析死锁（循环依赖） | 低 | plan_node 的 prompt 要求 LLM 输出 DAG（监督约束：循环依赖 = 拒绝执行并提示用户） |

---

## 9. 从 v1.0 的迁移清单

| v1.0 文件 | v2.0 去向 |
|-----------|-----------|
| `common/config.py` | 直接复用，扩展 AgentRegistry 配置项 |
| `common/db.py` | 直接复用 |
| `common/llm.py` | 直接复用 |
| `common/log.py` | 直接复用 |
| `common/agent_loop.py` | 直接复用（Local Adapter 用） |
| `a2a_infra/client.py` | 废弃，改用 a2a-sdk 1.0 原生 API |
| `a2a_infra/server.py` | 废弃，1.0 Server API 完全不同 |
| `a2a_infra/executor.py` | 废弃，1.0 AgentExecutor 接口变化 |
| `agents/*` | 废弃，业务不匹配 |
| `host/graph.py` | 参考系统提示词风格，架构完全重写 |
| `host/remote_tools.py` | AgentCard→工具转译思路可参考，但适配器模式替代 |
| `host/cli.py` | REPL 模式可复用 |
| `tests/conftest.py` | FakeLLM fixture 可复用 |
| `tests/integration/conftest.py` | 真实起服务的 fixture 模式可复用 |
| `docs/` | 文档模板可复用 |
| `docker/` | Dockerfile 模式可复用 |
