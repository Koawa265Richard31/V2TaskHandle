"use client";

// 首次启动身份设定模态框:填名字 + 选组长/组员
import { useState } from "react";

interface Identity {
  name: string;
  role: "leader" | "member";
}

interface IdentityModalProps {
  initial: Identity;
  onConfirm: (ident: Identity) => void;
}

export default function IdentityModal({ initial, onConfirm }: IdentityModalProps) {
  const [name, setName] = useState(initial.name);
  const [role, setRole] = useState<"leader" | "member">(initial.role);

  const handleConfirm = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onConfirm({ name: trimmed, role });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div
        className="w-full max-w-md rounded-2xl p-8 shadow-2xl"
        style={{ backgroundColor: "var(--surface-container-high)", border: "1px solid var(--outline-variant)" }}
      >
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full" style={{ background: "var(--primary-faint)" }}>
            <span className="material-symbols-outlined text-3xl" style={{ color: "var(--primary)" }}>
              smart_toy
            </span>
          </div>
          <h2 className="font-headline-md text-headline-md text-on-surface">欢迎使用 Task Orchestrator</h2>
          <p className="mt-1 text-sm text-on-surface-variant">设置你的身份以开始协作</p>
        </div>

        {/* 名字 */}
        <div className="mb-5">
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-on-surface-variant">
            你的名字
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleConfirm()}
            placeholder="例如: 张三"
            autoFocus
            className="w-full rounded-lg border px-3 py-2.5 text-sm text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-2"
            style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--outline-variant)", ["--tw-ring-color" as string]: "var(--primary)" }}
          />
        </div>

        {/* 角色 */}
        <div className="mb-6">
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-on-surface-variant">
            角色
          </label>
          <div className="space-y-2">
            <label
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-all ${
                role === "leader" ? "border-primary bg-primary-faint" : "border-outline-variant"
              }`}
              style={
                role === "leader"
                  ? { borderColor: "var(--primary)", backgroundColor: "var(--primary-faint)" }
                  : { borderColor: "var(--outline-variant)" }
              }
            >
              <input
                type="radio"
                name="role"
                value="leader"
                checked={role === "leader"}
                onChange={() => setRole("leader")}
                className="mt-0.5 accent-[var(--primary)]"
              />
              <div>
                <div className="text-sm font-medium text-on-surface">组长 (Leader)</div>
                <div className="mt-0.5 text-xs text-on-surface-variant">创建团队，分派任务，管理成员</div>
              </div>
            </label>
            <label
              className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-all ${
                role === "member" ? "border-primary bg-primary-faint" : "border-outline-variant"
              }`}
              style={
                role === "member"
                  ? { borderColor: "var(--primary)", backgroundColor: "var(--primary-faint)" }
                  : { borderColor: "var(--outline-variant)" }
              }
            >
              <input
                type="radio"
                name="role"
                value="member"
                checked={role === "member"}
                onChange={() => setRole("member")}
                className="mt-0.5 accent-[var(--primary)]"
              />
              <div>
                <div className="text-sm font-medium text-on-surface">组员 (Member)</div>
                <div className="mt-0.5 text-xs text-on-surface-variant">加入团队，接收并执行任务</div>
              </div>
            </label>
          </div>
        </div>

        <button
          onClick={handleConfirm}
          disabled={!name.trim()}
          className="w-full cursor-pointer rounded-lg px-4 py-2.5 text-sm font-medium transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          style={{ backgroundColor: "var(--primary)", color: "var(--on-primary)" }}
        >
          开始使用
        </button>
      </div>
    </div>
  );
}
