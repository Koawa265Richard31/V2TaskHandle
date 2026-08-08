"use client";

// 聊天区:欢迎区 + 消息流 + 底部输入
import { useRef, useState } from "react";
import type { ChatMessage } from "@/hooks/useChat";

interface ChatViewProps {
  messages: ChatMessage[];
  streaming: boolean;
  onSend: (text: string) => void;
  onNewSession: () => void;
}

export default function ChatView({ messages, streaming, onSend, onNewSession }: ChatViewProps) {
  const [input, setInput] = useState("");
  const [entered, setEntered] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = (text: string) => {
    if (!text.trim()) return;
    onSend(text);
    setInput("");
    setEntered(true);
  };

  return (
    <div className="relative flex flex-1 flex-col p-6">
      {/* 欢迎区 */}
      {!entered && messages.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center transition-all duration-500">
          <h2
            className="font-display-lg mb-3 shiny-text"
            style={{
              color: "var(--primary)",
              fontSize: 42,
              fontWeight: 700,
              letterSpacing: "-0.02em",
            }}
          >
            Agent Orchestrator
          </h2>
          <p className="font-body-md mb-8 text-[15px] text-on-surface-variant">尽管问，或做个 Agent 任务…</p>
          {/* 居中输入框 */}
          <div className="glass-panel w-full max-w-2xl overflow-hidden rounded-full transition-all duration-300 focus-within:glow-active focus-within:bg-surface-container-high">
            <div className="relative">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    submit(input);
                  }
                }}
                placeholder="把任务交给我…"
                className="w-full bg-transparent px-6 py-4 font-body-lg text-body-lg text-on-surface focus:ring-0"
                type="text"
              />
              <button
                onClick={() => submit(input)}
                className="absolute right-2 top-2 bottom-2 flex h-10 w-10 cursor-pointer items-center justify-center rounded-full bg-primary/10 text-primary transition-colors hover:bg-primary/20"
              >
                <span className="material-symbols-outlined text-[20px]">send</span>
              </button>
            </div>
          </div>
        </div>
      ) : (
        <>
          {/* 消息流 */}
          <div className="flex-1 space-y-6 overflow-y-auto pb-24 pr-4 scrollbar-thin">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`glass-panel relative max-w-[85%] rounded-2xl px-5 py-4 ${
                    m.role === "user" ? "rounded-tr-sm" : "rounded-tl-sm"
                  }`}
                >
                  {m.role === "assistant" && (
                    <div className="absolute left-0 top-3 bottom-3 w-[3px] rounded-r bg-secondary" />
                  )}
                  <p className={`font-body-lg text-body-lg text-on-surface ${streaming && i === messages.length - 1 && m.role === "assistant" && !m.content ? "typing-cursor" : ""}`}>
                    {m.content || (streaming ? "正在思考…" : "")}
                  </p>
                </div>
              </div>
            ))}
          </div>
          {/* 底部输入 */}
          <div className="absolute bottom-6 left-6 right-6 transition-all duration-500">
            <div className="glass-panel relative overflow-hidden rounded-full transition-all duration-300 focus-within:glow-active focus-within:bg-surface-container-high">
              <div className="flex items-center">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      submit(input);
                    }
                  }}
                  placeholder="把任务交给我…"
                  className="w-full bg-transparent px-6 py-4 font-body-lg text-body-lg text-on-surface focus:ring-0"
                  type="text"
                />
                <button
                  onClick={() => submit(input)}
                  className="absolute right-2 top-2 bottom-2 flex h-10 w-10 cursor-pointer items-center justify-center rounded-full bg-primary/10 text-primary transition-colors hover:bg-primary/20"
                >
                  <span className="material-symbols-outlined text-[20px]">send</span>
                </button>
              </div>
            </div>
            {messages.length > 0 && (
              <div className="mt-2 flex justify-center">
                <button
                  onClick={onNewSession}
                  className="cursor-pointer rounded-lg px-3 py-1 text-xs text-on-surface-variant transition-colors hover:bg-surface-variant/10"
                >
                  新会话
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
