"use client";

import { useState } from "react";
import { useSSEChat } from "@/hooks/use-sse-chat";
import { useRegistry } from "@/hooks/use-registry";
import type { SubTask, RegistryStatus } from "@/lib/types";

export default function HomePage() {
  const { messages, plan, streaming, sessionId, error, agents, sendMessage, newSession, stop } = useSSEChat();
  const registry = useRegistry();
  const [teamOpen, setTeamOpen] = useState(false);

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const input = (e.target as HTMLFormElement).querySelector("textarea") as HTMLTextAreaElement;
    if (input?.value.trim()) {
      sendMessage(input.value);
      input.value = "";
      input.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent<HTMLFormElement>);
    }
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="h-14 flex items-center justify-between px-5 border-b shrink-0" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-sm font-bold" style={{ background: "var(--color-accent)" }}>T</div>
          <span className="font-semibold text-sm tracking-tight">Task Orchestrator</span>
          <div className="flex items-center gap-2 ml-2">
            {(["a2a", "codex", "local"] as const).map(type => {
              const agent = agents.find(a => a.type === type);
              const color = agent?.status === "online" ? "var(--color-success)" :
                agent?.status === "busy" ? "var(--color-warn)" : "var(--color-text-muted)";
              return (
                <span key={type} className="flex items-center gap-1 text-[11px]" style={{ color: "var(--color-text-dim)" }}>
                  <span className="w-[6px] h-[6px] rounded-full inline-block" style={{ backgroundColor: color }} />
                  {type}
                </span>
              );
            })}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {streaming && (
            <button onClick={stop} className="text-xs px-3 py-1.5 rounded-lg border transition-colors hover:opacity-80" style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}>
              停止
            </button>
          )}
          <button onClick={() => setTeamOpen(v => !v)} className="text-xs px-3 py-1.5 rounded-lg border transition-colors hover:opacity-80" style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}>
            团队
            {registry.status?.requests?.length > 0 && (
              <span className="ml-1.5 px-1.5 py-0.5 rounded-full text-[10px]" style={{ backgroundColor: "var(--color-warn)", color: "#000" }}>
                {registry.status.requests.length}
              </span>
            )}
          </button>
          <button onClick={newSession} className="text-xs px-3 py-1.5 rounded-lg border transition-colors hover:opacity-80" style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}>
            新对话
          </button>
        </div>
      </header>

      {teamOpen && <TeamPanel registry={registry.status} onApprove={registry.approve} onClose={() => setTeamOpen(false)} />}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages */}
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {messages.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="max-w-3xl mx-auto py-6 px-4 space-y-6">
                {messages.map(msg => (
                  <MessageBubble key={msg.id} message={msg} />
                ))}
                {error && (
                  <div className="animate-in text-center py-3 px-4 rounded-lg text-sm mx-auto max-w-lg" style={{ background: "rgba(239,68,68,0.1)", color: "var(--color-error)", border: "1px solid rgba(239,68,68,0.2)" }}>
                    {error}
                  </div>
                )}
                <div className="h-4" />
              </div>
            )}
          </div>

          {/* Input */}
          <div className="shrink-0 border-t px-4 py-3" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
            <form onSubmit={handleSubmit} className="max-w-3xl mx-auto">
              <div className="flex gap-2 items-end p-2 rounded-xl border transition-colors" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface-alt)" }}>
                <textarea
                  rows={1}
                  placeholder="输入任务或消息..."
                  onKeyDown={handleKeyDown}
                  onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 200) + "px"; }}
                  disabled={streaming}
                  className="flex-1 bg-transparent resize-none text-sm outline-none py-1 px-2 placeholder-gray-500 disabled:opacity-50"
                  style={{ color: "var(--color-text)" }}
                />
                <button
                  type="submit"
                  disabled={streaming}
                  className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors disabled:opacity-30"
                  style={{ backgroundColor: "var(--color-accent)", color: "#fff" }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Task Panel */}
        {plan.length > 0 && (
          <div className="w-80 shrink-0 border-l overflow-y-auto scrollbar-thin" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
            <div className="px-4 py-3 border-b text-sm font-medium flex items-center justify-between" style={{ borderColor: "var(--color-border)" }}>
              <span>任务计划</span>
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: "var(--color-surface-alt)", color: "var(--color-text-dim)" }}>
                {plan.filter(t => t.status === "completed").length}/{plan.length}
              </span>
            </div>
            <div className="p-3 space-y-2">
              {plan.map(task => (
                <TaskCard key={task.task_id} task={task} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <footer className="h-7 flex items-center justify-between px-4 text-[11px] border-t shrink-0" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)", color: "var(--color-text-muted)" }}>
        <span>{sessionId ? `会话 ${sessionId.slice(0, 8)}` : "新会话"}</span>
        <span>{streaming && <span className="animate-pulse">生成中...</span>}</span>
      </footer>
    </div>
  );
}

function TeamPanel({ registry, onApprove, onClose }: {
  registry: RegistryStatus | null;
  onApprove: (id: number, ok: boolean) => Promise<boolean>;
  onClose: () => void;
}) {
  const isLeader = registry?.role === "leader";
  return (
    <div className="absolute right-5 top-16 z-50 w-80 rounded-xl border shadow-xl" style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)" }}>
      <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: "var(--color-border)" }}>
        <span className="text-sm font-semibold">团队协作</span>
        <button onClick={onClose} className="text-xs px-2 py-0.5 rounded hover:opacity-70" style={{ color: "var(--color-text-dim)" }}>✕</button>
      </div>

      <div className="p-4 space-y-4 max-h-80 overflow-y-auto">
        {/* 注册状态 */}
        <div className="text-xs" style={{ color: "var(--color-text-dim)" }}>
          {registry?.registered ? (
            <span style={{ color: "var(--color-success)" }}>● 已注册 (ID: {registry.peer_id})</span>
          ) : (
            <span style={{ color: "var(--color-text-muted)" }}>○ 未注册到注册中心</span>
          )}
          <div className="mt-0.5">角色: {isLeader ? "组长" : "组员"}</div>
        </div>

        {/* 组长:待批准请求 */}
        {isLeader && (
          <div>
            <div className="text-[11px] font-medium mb-1.5" style={{ color: "var(--color-text-dim)" }}>待批准申请</div>
            {registry?.requests?.length === 0 ? (
              <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>暂无待批准申请</div>
            ) : (
              registry?.requests?.map(r => (
                <div key={r.id} className="mb-2 p-2.5 rounded-lg text-xs" style={{ backgroundColor: "var(--color-surface-alt)", border: "1px solid var(--color-border)" }}>
                  <div className="font-medium" style={{ color: "var(--color-text)" }}>{r.peer_name}</div>
                  <div className="mt-0.5" style={{ color: "var(--color-text-muted)" }}>{r.peer_url}</div>
                  <div className="mt-2 flex gap-2">
                    <button onClick={() => onApprove(r.id, true)} className="px-2.5 py-1 rounded-md text-[11px]" style={{ backgroundColor: "var(--color-success)", color: "#000" }}>
                      批准
                    </button>
                    <button onClick={() => onApprove(r.id, false)} className="px-2.5 py-1 rounded-md text-[11px] border" style={{ borderColor: "var(--color-error)", color: "var(--color-error)" }}>
                      拒绝
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* 已批准组员(组长视角) */}
        {isLeader && (
          <div>
            <div className="text-[11px] font-medium mb-1.5" style={{ color: "var(--color-text-dim)" }}>已加入团队</div>
            {registry?.approved_peers?.length === 0 ? (
              <div className="text-xs" style={{ color: "var(--color-text-muted)" }}>暂无已批准的组员</div>
            ) : (
              registry?.approved_peers?.map(p => (
                <div key={p.peer_id} className="flex items-center gap-2 mb-1.5 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: "var(--color-success)" }} />
                  <span style={{ color: "var(--color-text)" }}>{p.name}</span>
                  <span className="ml-auto truncate" style={{ color: "var(--color-text-muted)" }}>{p.url}</span>
                </div>
              ))
            )}
          </div>
        )}

        {/* 组员:申请状态 */}
        {!isLeader && (
          <div className="text-xs" style={{ color: "var(--color-text-dim)" }}>
            {registry?.registry_url ? (
              <span>已连接注册中心 {registry.registry_url}</span>
            ) : (
              <span style={{ color: "var(--color-text-muted)" }}>未配置注册中心 (PTA_REGISTRY_URL)</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  const suggestions = [
    "帮我创建一个任务：明天下午3点提交周报，高优先级",
    "提醒我周五上午10点开周会",
    "帮我分析当前项目的代码结构",
    "你好，你能做什么？",
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full px-4 animate-in">
      <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl mb-6" style={{ background: "linear-gradient(135deg, var(--color-accent), #a855f7)" }}>
        ⚡
      </div>
      <h2 className="text-lg font-semibold mb-2">Task Orchestrator</h2>
      <p className="text-sm mb-8" style={{ color: "var(--color-text-dim)" }}>多 Agent 任务编排 — 试试这些：</p>
      <div className="grid grid-cols-2 gap-2 max-w-md">
        {suggestions.map((s, i) => (
          <SuggestionButton key={i} text={s} onClick={() => {
            const form = document.querySelector("form") as HTMLFormElement;
            const textarea = form?.querySelector("textarea") as HTMLTextAreaElement;
            if (textarea) {
              textarea.value = s;
              form?.requestSubmit();
            }
          }} />
        ))}
      </div>
    </div>
  );
}

function SuggestionButton({ text, onClick }: { text: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="text-left text-xs p-3 rounded-lg border transition-all hover:scale-[1.02] truncate"
      style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)", backgroundColor: "var(--color-surface-alt)" }}
    >
      {text}
    </button>
  );
}

function MessageBubble({ message }: { message: { id: string; role: string; content: string; is_streaming: boolean; plan: SubTask[] | null } }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""} animate-in`}>
      <div
        className="w-8 h-8 rounded-lg shrink-0 flex items-center justify-center text-xs font-bold"
        style={isUser ? { backgroundColor: "var(--color-user-bg)", color: "#a5b4fc" } : { backgroundColor: "var(--color-accent)", color: "#fff" }}
      >
        {isUser ? "U" : "T"}
      </div>
      <div className={`flex-1 ${isUser ? "flex flex-col items-end" : ""} max-w-[85%]`}>
        <div
          className="text-sm leading-relaxed whitespace-pre-wrap px-4 py-2.5 rounded-2xl"
          style={isUser ? {
            backgroundColor: "var(--color-user-bg)",
            color: "var(--color-text)",
            borderBottomRightRadius: "4px",
          } : {
            backgroundColor: "var(--color-surface-alt)",
            color: "var(--color-text)",
            borderBottomLeftRadius: "4px",
          }}
        >
          {message.content || (message.is_streaming ? <span className="typing-cursor" /> : "")}
        </div>
        {message.plan && message.plan.length > 0 && (
          <div className="mt-2 w-full rounded-xl p-3 space-y-1.5" style={{ backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)" }}>
            <div className="text-[11px] font-medium mb-1" style={{ color: "var(--color-text-dim)" }}>执行计划</div>
            {message.plan.map(t => (
              <div key={t.task_id} className="flex items-center gap-2 text-xs">
                <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: statusColor(t.status) }} />
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={badgeStyle(t.agent_type)}>{t.agent_type}</span>
                <span style={{ color: "var(--color-text-dim)" }}>{t.description.slice(0, 40)}</span>
                <span className="ml-auto text-[10px]" style={{ color: "var(--color-text-muted)" }}>{statusLabel(t.status)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TaskCard({ task }: { task: SubTask }) {
  const colors: Record<string, { bg: string; border: string; dot: string }> = {
    completed: { bg: "rgba(34,197,94,0.05)", border: "rgba(34,197,94,0.2)", dot: "var(--color-success)" },
    running: { bg: "rgba(234,179,8,0.05)", border: "rgba(234,179,8,0.2)", dot: "var(--color-warn)" },
    failed: { bg: "rgba(239,68,68,0.05)", border: "rgba(239,68,68,0.2)", dot: "var(--color-error)" },
    pending: { bg: "transparent", border: "var(--color-border)", dot: "var(--color-text-muted)" },
    ready: { bg: "transparent", border: "rgba(99,102,241,0.3)", dot: "var(--color-accent)" },
    canceled: { bg: "transparent", border: "var(--color-border)", dot: "var(--color-text-muted)" },
  };
  const c = colors[task.status] || colors.pending;

  return (
    <div className="p-3 rounded-lg text-xs" style={{ border: `1px solid ${c.border}`, backgroundColor: c.bg }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={badgeStyle(task.agent_type)}>{task.agent_type}</span>
        <span className="flex items-center gap-1 text-[10px]" style={{ color: "var(--color-text-muted)" }}>
          <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: c.dot }} />
          {statusLabel(task.status)}
        </span>
      </div>
      <div style={{ color: "var(--color-text)" }}>{task.description}</div>
      {task.dependencies.length > 0 && (
        <div className="mt-1" style={{ color: "var(--color-text-muted)" }}>依赖: {task.dependencies.join(", ")}</div>
      )}
      {task.result && (
        <div className="mt-2 pt-1.5 border-t text-[11px] leading-relaxed" style={{ borderColor: "var(--color-border)", color: "var(--color-text-dim)" }}>
          {task.result.slice(0, 200)}
        </div>
      )}
      {task.error && (
        <div className="mt-1 text-[11px]" style={{ color: "var(--color-error)" }}>{task.error.slice(0, 100)}</div>
      )}
    </div>
  );
}

function statusColor(s: string) {
  const map: Record<string, string> = { completed: "var(--color-success)", running: "var(--color-warn)", failed: "var(--color-error)", ready: "var(--color-accent)" };
  return map[s] || "var(--color-text-muted)";
}

function statusLabel(s: string) {
  const map: Record<string, string> = { pending: "等待", ready: "就绪", running: "执行中", completed: "完成", failed: "失败", canceled: "已取消" };
  return map[s] || s;
}

function badgeStyle(t: string) {
  const map: Record<string, { background: string; color: string }> = {
    a2a: { background: "rgba(59,130,246,0.15)", color: "#93c5fd" },
    codex: { background: "rgba(168,85,247,0.15)", color: "#c4b5fd" },
    local: { background: "rgba(34,197,94,0.15)", color: "#86efac" },
  };
  const s = map[t] || { background: "rgba(107,114,128,0.15)", color: "#9ca3af" };
  return { backgroundColor: s.background, color: s.color, border: "none" };
}
