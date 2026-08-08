"use client";

// SSE 聊天 hook:迁移自 console.html 的 sendMessage + renderDag 逻辑
// POST /api/chat → ReadableStream 解析 plan/message/task_*/done 事件
import { useCallback, useRef, useState } from "react";

export type TaskStatus =
  | "pending"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "canceled"
  | "waiting_approval";

export interface SubTask {
  task_id: string;
  description: string;
  agent_type: string;
  agent_target?: string;
  dependencies: string[];
  status: TaskStatus;
  result?: string | null;
  error?: string | null;
  approval_mode?: string;
  progress?: string | null;
  requires_monitor?: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function statusColor(s: TaskStatus): string {
  const m: Record<string, string> = {
    completed: "#34d399",
    running: "#f59e0b",
    failed: "#f87171",
    waiting_approval: "#f87171",
    pending: "#908fa0",
    ready: "#a99ff0",
  };
  return m[s] || "#908fa0";
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [plan, setPlan] = useState<SubTask[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  const updatePlan = useCallback((next: SubTask[]) => {
    setPlan(next);
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || streaming) return;
      setMessages((prev) => [...prev, { role: "user", content: text }]);
      setStreaming(true);
      setError(null);

      // 占位 assistant 消息
      const assistantIdx = messages.length;
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      let assistantText = "";
      try {
        const resp = await fetch(`${API_URL}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            session_id: sessionIdRef.current,
          }),
        });
        if (!resp.body) throw new Error("响应无 body");
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          let evt = "";
          for (const line of lines) {
            if (line.startsWith("event: ")) {
              evt = line.slice(7).trim();
              continue;
            }
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6);
            if (raw === "[DONE]") continue;
            try {
              const d = JSON.parse(raw);
              if (evt === "plan") {
                setPlan(d.tasks);
              } else if (evt === "message") {
                assistantText += d.delta || "";
                setMessages((prev) => {
                  const next = [...prev];
                  const last = next[next.length - 1];
                  if (last && last.role === "assistant") {
                    next[next.length - 1] = { ...last, content: assistantText };
                  }
                  return next;
                });
              } else if (
                evt === "task_update" ||
                evt === "task_complete" ||
                evt === "task_fail" ||
                evt === "task_waiting_approval"
              ) {
                setPlan((prev) => {
                  if (!prev.length) return prev;
                  return prev.map((t) =>
                    t.task_id === d.task_id
                      ? {
                          ...t,
                          status:
                            evt === "task_complete"
                              ? "completed"
                              : evt === "task_fail"
                                ? "failed"
                                : evt === "task_waiting_approval"
                                  ? "waiting_approval"
                                  : (d.status as TaskStatus),
                          result: d.result ?? t.result,
                          error: d.error ?? t.error,
                        }
                      : t,
                  );
                });
              } else if (evt === "done") {
                setSessionId(d.session_id);
                sessionIdRef.current = d.session_id;
              }
            } catch {
              // 忽略单行解析错误
            }
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === "assistant" && !last.content) {
            next[next.length - 1] = { ...last, content: "错误: " + (e instanceof Error ? e.message : e) };
          }
          return next;
        });
      } finally {
        setStreaming(false);
      }
      void assistantIdx;
    },
    [messages.length, streaming],
  );

  const newSession = useCallback(() => {
    setMessages([]);
    setPlan([]);
    setSessionId(null);
    sessionIdRef.current = null;
  }, []);

  return { messages, plan, streaming, sessionId, error, sendMessage, newSession, updatePlan };
}
