# 前端 GUI 设计规范书

> 框架：Next.js 15 (App Router) + React 19 + TypeScript + shadcn/ui + Tailwind CSS 4
> 通信：Vercel AI SDK (SSE) ← Python FastAPI ← LangGraph
> 日期：2026-08-01

---

## 1. 项目结构

```
frontend/
├── package.json
├── tsconfig.json
├── next.config.ts
├── tailwind.config.ts
├── components.json              # shadcn/ui init 生成
├── .env.local                   # NEXT_PUBLIC_API_URL=http://localhost:8000
├── public/
│   └── favicon.svg
├── app/
│   ├── layout.tsx               # RootLayout: providers + metadata
│   ├── page.tsx                  # 入口页: 双栏布局
│   ├── globals.css               # Tailwind + 暗色主题 CSS 变量
│   └── error.tsx                 # 错误边界
├── components/
│   ├── ui/                       # shadcn/ui 生成的组件
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── card.tsx
│   │   ├── badge.tsx
│   │   ├── scroll-area.tsx
│   │   ├── skeleton.tsx
│   │   ├── tooltip.tsx
│   │   ├── dialog.tsx
│   │   ├── separator.tsx
│   │   └── progress.tsx
│   ├── layout/
│   │   ├── app-shell.tsx         # 顶层双栏容器
│   │   ├── app-header.tsx        # 顶部:会话ID, Agent状态指示灯
│   │   └── app-footer.tsx        # 底部:命令行, 状态栏
│   ├── chat/
│   │   ├── chat-panel.tsx        # 左侧聊天面板容器
│   │   ├── chat-messages.tsx     # 消息列表(virtualized scroll)
│   │   ├── chat-input.tsx        # 输入框 + 发送按钮 + 快捷键
│   │   ├── message-bubble.tsx    # 单条消息(区分 user/assistant/system)
│   │   └── thinking-indicator.tsx # "正在规划..." 动画条
│   ├── tasks/
│   │   ├── task-panel.tsx        # 右侧任务面板容器
│   │   ├── task-card.tsx         # 单个子任务卡片
│   │   ├── task-dep-graph.tsx    # 任务依赖 DAG(简易 SVG 版)
│   │   └── empty-task-panel.tsx  # 空状态占位
│   └── agents/
│       ├── agent-status-bar.tsx  # Header 里的状态指示灯行
│       └── agent-mini-topo.tsx   # 微缩拓扑图(SVG)
├── hooks/
│   ├── use-chat.ts               # 核心: SSE 流式聊天 + 消息状态管理
│   ├── use-tasks.ts              # 任务面板状态(useReducer)
│   └── use-agents.ts             # Agent 注册列表轮询
├── lib/
│   ├── types.ts                  # 全部 TypeScript 类型定义
│   ├── api.ts                    # API 调用函数(POST /api/chat, GET /api/agents, etc.)
│   ├── sse.ts                    # SSE 解析器(ReadableStream → typed events)
│   └── utils.ts                  # 时间格式化, cn(), 状态色映射
└── __tests__/
    ├── use-chat.test.ts
    ├── task-card.test.tsx
    └── sse.test.ts
```

---

## 2. 类型系统 (`lib/types.ts`)

```typescript
// ── Agent 相关 ──

export type AgentType = 'a2a' | 'codex' | 'local';
export type AgentStatus = 'online' | 'offline' | 'busy';

export interface AgentInfo {
  type: AgentType;
  name: string;
  status: AgentStatus;
  url?: string;              // A2A only
  capabilities: string[];    // 从 AgentCard 或配置解析
}

// ── 子任务 ──

export type TaskStatus = 'pending' | 'ready' | 'running' | 'completed' | 'failed';

export interface SubTask {
  task_id: string;
  description: string;
  agent_type: AgentType;
  agent_target: string;      // A2A: url, Codex: sandbox, Local: tool_name
  dependencies: string[];    // 依赖的 task_id 列表
  status: TaskStatus;
  result: string | null;
  error: string | null;
  started_at: number | null; // unix ms
  ended_at: number | null;
}

// ── 聊天消息 ──

export type MessageRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  is_streaming: boolean;              // 是否还在 SSE 流中
  plan: SubTask[] | null;             // 关联的任务计划(assistant 消息专有)
}

// ── SSE 事件 ──

export type SSEEvent =
  | { type: 'plan'; tasks: SubTask[] }
  | { type: 'task_start'; task_id: string; agent_type: AgentType }
  | { type: 'task_update'; task_id: string; status: TaskStatus; message?: string }
  | { type: 'task_complete'; task_id: string; result: string }
  | { type: 'task_fail'; task_id: string; error: string }
  | { type: 'message'; delta: string }               // 流式文本增量
  | { type: 'message_end' }                           // 消息流结束
  | { type: 'done'; final_response: string | null }   // 整轮对话结束
  | { type: 'error'; message: string }
  | { type: 'agent_status'; agent_type: AgentType; status: AgentStatus };

// ── API 请求/响应 ──

export interface ChatRequest {
  message: string;
  session_id: string | null;  // null = 新会话
}

export interface ChatResponse {
  session_id: string;
}
```

---

## 3. 状态管理 (`hooks/`)

### 3.1 `use-chat.ts` — 核心状态机

```
State:
  messages: ChatMessage[]
  sessionId: string | null
  isStreaming: boolean
  currentPlan: SubTask[] | null
  error: string | null

Actions:
  sendMessage(text: string) → 调用 POST /api/chat, 打开 SSE 流
  newSession() → 清空 messages + sessionId
  clearError()

内部: SSE ReadableStream 逐事件解析 → dispatch 更新
```

流式消费逻辑:
```
POST /api/chat → Response.body.getReader() → SSE 逐行解析
  event: plan       → 更新 currentPlan
  event: message    → 追加到 latest assistant message.content
  event: task_*     → 更新 currentPlan 中对应 task 的 status
  event: done       → 标记 streaming=false
  event: error      → 设置 error 状态
```

### 3.2 `use-tasks.ts` — 任务面板

```typescript
// 从 use-chat 的 currentPlan 派生, 额外计算:
// - sortedTasks: 按依赖拓扑排序
// - readyCount / runningCount / completedCount / failedCount
// - hasFailures: boolean → 触发 replan 提示
```

### 3.3 `use-agents.ts` — Agent 列表

```typescript
// 启动时 GET /api/agents → 填充 AgentInfo[]
// 每 30s 轮询刷新状态
// SSE event:agent_status 事件也可更新
```

---

## 4. 页面与路由

| 路由 | 说明 |
|------|------|
| `/` | 主页面：双栏（聊天 + 任务面板） |
| `/sessions/[id]` | 恢复历史会话（可选，M6 实现） |

页面入口 `app/page.tsx` 结构：

```tsx
export default function HomePage() {
  return (
    <ChatProvider>        {/* use-chat context */}
      <TaskProvider>      {/* use-tasks context */}
        <AgentProvider>   {/* use-agents context */}
          <AppShell />    {/* 双栏布局 */}
        </AgentProvider>
      </TaskProvider>
    </ChatProvider>
  );
}
```

---

## 5. 组件详细规格

### 5.1 `AppShell` — 布局容器

```
┌───────────────────────────────────────────────────┐
│  AppHeader (h-12)                                 │
│  ┌─────────────────────┬─────────────────────────┐│
│  │ ChatPanel           │ TaskPanel               ││
│  │ (flex-1, 可 resize) │ (w-[400px], 可折叠)      ││
│  └─────────────────────┴─────────────────────────┘│
│  AppFooter (h-7)                                  │
└───────────────────────────────────────────────────┘
```

Props: 无（从 context 读取）
State:
- `rightPanelOpen: boolean` — 任务面板折叠/展开
- `rightPanelWidth: number` — 拖拽调整宽度

### 5.2 `AppHeader`

```
┌──────────────────────────────────────────────────┐
│ ■ TaskOrchestrator          ┌──┐┌──┐┌──┐  □ □  │
│                             │A2││Cx││Lo│ 折叠 新建│
│                             └──┘└──┘└──┘         │
└──────────────────────────────────────────────────┘
```

内部组件:
- `AgentStatusBar` — 三个 AgentType 指示灯
  - A2A: 绿色(online) / 灰色(offline) / 黄色(busy)
  - Codex: 同上
  - Local: 同上
  - hover 显示 tooltip: Agent 名字、capabilities
- 右侧按钮: 折叠任务面板、新建会话

### 5.3 `ChatPanel` — 聊天面板

```
┌─────────────────────────────────────┐
│ ChatMessages (flex-1, scroll-y)     │
│ ┌─────────────────────────────────┐ │
│ │ [User] 帮我整理本周工作           │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ [Assistant]                      │ │
│ │ 好的，我计划:                     │ │
│ │ 1. 分析代码提交记录 [Codex]       │ │
│ │ 2. 查询未完成任务 [A2A]          │ │
│ │ 3. 生成周报并发送 [Local]         │ │
│ │ 正在分配子任务... ████████░░      │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ Divider                            │
├─────────────────────────────────────┤
│ ChatInput (h-16)                   │
│ ┌─────────────────────────────────┐ │
│ │ [请输入...                ] [↵] │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

**ChatInput** 行为:
- Enter 发送, Shift+Enter 换行
- 发送中显示 loading spinner，禁用输入
- `/` 打开命令面板

### 5.4 `MessageBubble` — 消息气泡

```
Props:
  message: ChatMessage
  plan: SubTask[] | null    // assistant 消息可能带计划

三种形态:

[User]: 右对齐, 蓝色背景
[Assistant]: 左对齐, 灰色背景, markdown 渲染
  - 带 plan 时在消息下方内嵌 mini task 列表(只显示,不可交互)
[System]: 居中, 小字灰色, 用于 "会话已创建" "Agent 重新连接" 等
```

Streaming 中: assistant 消息末尾带闪烁光标 `▊`

### 5.5 `TaskPanel` — 任务面板

```
┌────────────────────────────┐
│ 任务计划          [展开]   │
├────────────────────────────┤
│ ┌────────────────────────┐ │
│ │ Task #1                │ │
│ │ 分析本周代码提交记录     │ │
│ │ [Codex] [████████░░]   │ │  ← 进度条
│ │ ⚡ running · 12s       │ │
│ └────────────────────────┘ │
│ ┌────────────────────────┐ │
│ │ Task #2                │ │
│ │ 查询未完成任务列表      │ │
│ │ [A2A]  ✅ completed    │ │
│ │ ✅ 3 tasks found       │ │
│ └────────────────────────┘ │
│ ┌────────────────────────┐ │
│ │ Task #3                │ │
│ │ 生成周报并发送邮件      │ │
│ │ [Local] ⬜ pending      │ │
│ │ 等待 Task #1, #2       │ │
│ └────────────────────────┘ │
├────────────────────────────┤
│ TaskDepGraph (mini SVG)    │
│  [#1]──┐                   │
│        ├──[#3 pending]    │
│  [#2]──┘                   │
├────────────────────────────┤
│ 进度: 1/3 完成             │
│ ⚡ 1 running · ✅ 1 done   │
└────────────────────────────┘
```

### 5.6 `TaskCard` — 任务卡片

```
Props:
  task: SubTask
  isLast: boolean

状态映射:

pending →  灰色边框, "[Local] ⬜ 等待中"
ready   →  蓝色边框, "[Codex] 🔵 已就绪"
running →  黄色边框, "[A2A] ⚡ 执行中 · 12s" + Progress 动画
completed→ 绿色边框, "[Codex] ✅ 完成 · 3.2s" + 结果内容折叠
failed  →  红色边框, "[Local] ❌ 失败" + 错误信息展开 + [重试] 按钮

卡内元素:
- Agent 图标 (☁ A2A / ⌨ Codex / ⚙ Local)
- 任务描述 (1-2 行, overflow ellipsis)
- 状态行 (icon + label + 耗时)
- 结果内容 (completed/failed 时展开, max-h collapse)
- 依赖等待提示 (pending 且 deps 未完成时)
```

### 5.7 `TaskDepGraph` — 依赖图

简易 SVG 实现(不引入 ReactFlow，保持轻量):

```
Props:
  tasks: SubTask[]

绘制逻辑:
1. 每个 task 是一个矩形节点(id + status + 前 8 字描述)
2. 依赖关系用带箭头线连接
3. completed=绿色, running=黄色, failed=红色, pending/ready=灰色
4. 垂直布局: 被依赖的在上, 依赖者在下方
5. 节点 click → scroll 到对应 TaskCard
```

### 5.8 `ThinkingIndicator` — 思考动画

在 ChatMessages 底部显示(Assistant 生成计划时):

```
┌──────────────────────────────────────┐
│ ● 正在分析你的请求...                │
│ ● 正在规划子任务...                  │
│ ● 正在分配给 Agent...               │
└──────────────────────────────────────┘
```

实现: 三条 line 依次出现 + 消失, 对应 plan 阶段的三步

---

## 6. SSE 协议详细格式

Python 后端 → 前端 SSE 事件流：

```
POST /api/chat
Content-Type: application/json
{"message": "帮我整理本周工作", "session_id": null}

Response:
Content-Type: text/event-stream

event: plan
data: {"tasks":[{"task_id":"1","description":"分析本周代码提交记录","agent_type":"codex","agent_target":"workspace_write","dependencies":[],"status":"pending"},{"task_id":"2","description":"查询本周未完成任务","agent_type":"a2a","agent_target":"http://localhost:10001","dependencies":[],"status":"pending"},{"task_id":"3","description":"基于代码变更和任务情况生成周报并发送","agent_type":"local","agent_target":"email_sender","dependencies":["1","2"],"status":"pending"}]}

event: message
data: {"delta":"好的，我来帮你整理本周工作。"}

event: message
data: {"delta":"\n\n第一步："}

event: message
data: {"delta":"分析代码提交，第二步：查询任务。"}

event: task_start
data: {"task_id":"1","agent_type":"codex"}

event: task_start
data: {"task_id":"2","agent_type":"a2a"}

event: task_update
data: {"task_id":"1","status":"running","message":"正在分析 git log..."}

event: task_update
data: {"task_id":"2","status":"running","message":"查询未完成任务..."}

event: task_complete
data: {"task_id":"2","result":"找到 3 个未完成任务：#5 提交报销单(high)、#8 准备周会(todo)、#12 更新文档(todo)"}

event: task_complete
data: {"task_id":"1","result":"本周共 12 次提交，主要改动：重构 a2a_infra 模块，新增集成测试 11 个，修复 2 个 bug"}

event: task_start
data: {"task_id":"3","agent_type":"local"}

event: task_update
data: {"task_id":"3","status":"running","message":"正在生成周报..."}

event: task_complete
data: {"task_id":"3","result":"周报已生成并发送至 manager@company.com，内容包含了代码变更摘要和任务进度"}

event: message
data: {"delta":"\n\n全部完成！本周工作总结如下：\n\n**代码方面**：本周 12 次提交..."}

event: message_end
data: {}

event: done
data: {"final_response":"全部完成！...", "session_id":"sess_abc123"}
```

---

## 7. shadcn/ui 组件清单与定制

### 需安装的组件

```bash
npx shadcn@latest add button input textarea card separator badge
npx shadcn@latest add scroll-area tooltip dialog dropdown-menu skeleton
npx shadcn@latest add progress tabs
```

### 全局主题 (`globals.css`)

```css
@import "tailwindcss";

@theme {
  /* 暗色主题（默认） */
  --color-bg-primary: #0a0a0f;
  --color-bg-secondary: #13131a;
  --color-bg-tertiary: #1a1a24;
  --color-border: #2a2a3a;
  --color-text-primary: #e4e4ec;
  --color-text-secondary: #8b8b9e;
  --color-text-muted: #5a5a6e;

  /* Agent 类型色 */
  --color-a2a: #3b82f6;       /* blue */
  --color-codex: #a855f7;     /* purple */
  --color-local: #22c55e;     /* green */

  /* 状态色 */
  --color-status-online: #22c55e;
  --color-status-busy: #eab308;
  --color-status-offline: #6b7280;

  /* 任务状态 */
  --color-task-pending: #6b7280;
  --color-task-ready: #3b82f6;
  --color-task-running: #eab308;
  --color-task-completed: #22c55e;
  --color-task-failed: #ef4444;

  /* 字体 */
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --font-sans: 'Inter', system-ui, sans-serif;
}
```

### Agent 类型图标的 SVG 组件

不引入 icon 库（减少依赖），纯 SVG：

```tsx
// components/agents/agent-icon.tsx
export function AgentIcon({ type, size = 16 }: { type: AgentType; size?: number }) {
  const paths = {
    a2a: "M3 15a2 2 0 012-2h14a2 2 0 012 2v...",   // cloud icon
    codex: "M14.7 6.3a1 1 0 000...",               // terminal icon
    local: "M10.33 4.23a1 1 0 011.34 0...",        // gear icon
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor">
    <path d={paths[type]} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}
```

---

## 8. 关键交互细节

### 8.1 新会话时清空

- 点击 Header 的 "新建" 按钮 → `useChat.newSession()`
- 清空 messages + currentPlan + 重置 sessionId
- 聚焦 ChatInput

### 8.2 子任务失败后的重试

- TaskCard 显示红色边框 + 错误信息 + `[重试]` 按钮
- 点击重试 → POST `/api/tasks/{task_id}/retry` → 该 task 重新进入 running
- 或由 Main Agent 自动 replan（SSE event:replan 推送新计划）

### 8.3 命令面板 (`/` 快捷键)

```
命令:
/sessions   列出历史会话
/agents     查看注册的 Agent
/retry      重试最后一个失败的任务
/stop       停止当前执行
/help       帮助
```

### 8.4 响应式

- 桌面优先 (1280px+): 双栏布局
- 中等屏幕 (768-1280px): 聊天全宽，任务面板作为侧拉抽屉
- 移动端 (<768px): 聊天全屏，任务面板底部 Sheet

---

## 9. 后端 FastAPI 层 (`src/task_orchestrator/api/`)

```python
# src/task_orchestrator/api/
# ├── __init__.py
# ├── server.py          # FastAPI app + CORS + 路由
# ├── chat.py            # POST /api/chat SSE endpoint
# ├── agents.py          # GET /api/agents
# └── tasks.py           # GET /api/tasks/{session_id}, POST /api/tasks/{id}/retry
```

### 9.1 `server.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Task Orchestrator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
from task_orchestrator.api.chat import router as chat_router
from task_orchestrator.api.agents import router as agents_router
from task_orchestrator.api.tasks import router as tasks_router

app.include_router(chat_router)
app.include_router(agents_router)
app.include_router(tasks_router)
```

### 9.2 `chat.py` — SSE 核心

```python
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None

async def event_stream(message: str, session_id: str | None):
    """从 LangGraph 图生成 SSE 事件流。"""
    graph = get_main_agent_graph()
    config = {"configurable": {"thread_id": session_id or generate_session_id()}}

    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=message)]},
        config,
        version="v2",
    ):
        kind = event["event"]
        name = event["name"]

        if kind == "on_chat_model_stream":
            # LLM token streaming
            chunk = event["data"]["chunk"]
            yield sse("message", {"delta": chunk.content})

        elif kind == "on_chain_end" and name == "plan_node":
            # 计划节点完成 → 推送任务列表
            tasks = event["data"]["output"].get("tasks", [])
            yield sse("plan", {"tasks": [t.to_dict() for t in tasks]})

        elif kind == "on_chain_start" and name.startswith("dispatch_"):
            # 子任务提交
            task_id = event["data"].get("task_id")
            agent_type = event["data"].get("agent_type")
            yield sse("task_start", {"task_id": task_id, "agent_type": agent_type})

        # ... 更多事件映射

    yield sse("done", {"final_response": final_text, "session_id": session_id})


def sse(event: str, data: dict):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/api/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        event_stream(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
```

---

## 10. 开发工作流

### 10.1 初始化

```bash
# 前端
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir=false
cd frontend
npx shadcn@latest init     # 选: TypeScript, Tailwind 4, CSS variables, Zinc color
npx shadcn@latest add button input textarea card separator badge scroll-area tooltip dialog progress skeleton

# 后端
cd ../
# 已有 pyproject.toml，同时启动 FastAPI
```

### 10.2 并行开发

```bash
# 终端 1: Python 后端
uvicorn task_orchestrator.api.server:app --port 8000 --reload

# 终端 2: Next.js 前端
cd frontend && npm run dev     # :3000
```

### 10.3 测试

```bash
# 前端
cd frontend && npx vitest run

# 后端
pytest tests/ --tb=short
```

---

## 11. 降级策略

| 场景 | 处理 |
|------|------|
| Python 后端不可达 | 显示 "后端离线" banner，禁用输入框，每 5s 重试 |
| SSE 连接中断 | 自动重连（带指数退避），显示 "重新连接中..." |
| 某个 Agent 离线 | 对应指示灯变灰，该类型任务 plan 时提示 "xx Agent 不可用" |
| 前端无数据 | Skeleton loading 状态页 |
| 代码执行中用户关了网页 | 下次打开时从 checkpointer 恢复状态 |
