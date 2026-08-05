"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import type { ChatMessage, SubTask, AgentInfo } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useSSEChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [plan, setPlan] = useState<SubTask[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/agents`)
      .then(r => r.json())
      .then(setAgents)
      .catch(() => {});
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return;
    setError(null);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: Date.now(),
      is_streaming: false,
      plan: null,
    };

    const assistantId = crypto.randomUUID();
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      timestamp: Date.now(),
      is_streaming: true,
      plan: null,
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
        signal: controller.signal,
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let eventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith("data: ")) continue;

          const raw = line.slice(6);
          if (raw === "[DONE]") continue;

          try {
            const data = JSON.parse(raw);
            switch (eventType || data.type) {
              case "plan":
                setPlan(data.tasks);
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? { ...m, plan: data.tasks } : m
                ));
                break;
              case "task_update":
                setPlan(prev => prev.map(t =>
                  t.task_id === data.task_id ? { ...t, status: data.status } : t
                ));
                break;
              case "task_complete":
                setPlan(prev => prev.map(t =>
                  t.task_id === data.task_id ? { ...t, status: "completed", result: data.result } : t
                ));
                break;
              case "task_fail":
                setPlan(prev => prev.map(t =>
                  t.task_id === data.task_id ? { ...t, status: "failed", error: data.error } : t
                ));
                break;
              case "message":
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? { ...m, content: m.content + (data.delta || "") } : m
                ));
                break;
              case "done":
                setSessionId(data.session_id || sessionId);
                break;
              case "error":
                setError(data.message);
                setMessages(prev => prev.map(m =>
                  m.id === assistantId ? { ...m, content: m.content + `\n\n错误: ${data.message}`, is_streaming: false } : m
                ));
                break;
            }
            eventType = "";
          } catch {
            // skip malformed JSON
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      const msg = e instanceof Error ? e.message : "Network error";
      setError(msg);
      setMessages(prev => prev.map(m =>
        m.id === assistantId ? { ...m, is_streaming: false } : m
      ));
    }

    setMessages(prev => prev.map(m =>
      m.id === assistantId ? { ...m, is_streaming: false } : m
    ));
    setStreaming(false);
  }, [streaming, sessionId]);

  const newSession = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setPlan([]);
    setSessionId(null);
    setError(null);
    setStreaming(false);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setMessages(prev => prev.map(m =>
      m.is_streaming ? { ...m, is_streaming: false } : m
    ));
  }, []);

  return { messages, plan, streaming, sessionId, error, agents, sendMessage, newSession, stop };
}
