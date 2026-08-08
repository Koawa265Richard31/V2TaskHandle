"use client";

// 左侧导航栏:logo / nav / agents 分组 / 用户 popover
import { useEffect, useRef, useState } from "react";
import type { AgentInfo } from "@/hooks/useAgents";

interface SidebarProps {
  agents: AgentInfo[];
  cloudAgents: AgentInfo[];
  localAgents: AgentInfo[];
  activeView: string;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSwitchView: (view: string) => void;
  onOpenSettings: () => void;
}

function StatusDot({ status }: { status?: string }) {
  const color =
    status === "busy" ? "#f59e0b" : status === "online" || status === "available" ? "#34d399" : "#908fa0";
  const isBusy = status === "busy";
  if (isBusy) {
    return (
      <span
        className="h-3 w-3 animate-spin rounded-full border-2"
        style={{ borderColor: "#f59e0b", borderTopColor: "transparent" }}
      />
    );
  }
  return <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />;
}

export default function Sidebar({
  agents,
  cloudAgents,
  localAgents,
  activeView,
  collapsed,
  onToggleCollapsed,
  onSwitchView,
  onOpenSettings,
}: SidebarProps) {
  const [agentsOpen, setAgentsOpen] = useState(false);
  const [cloudOpen, setCloudOpen] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // 点击页面其他位置关闭用户 popover(与原版 document click 监听一致)
  useEffect(() => {
    if (!userMenuOpen) return;
    function onClickOutside(e: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener("click", onClickOutside);
    return () => document.removeEventListener("click", onClickOutside);
  }, [userMenuOpen]);

  const navItemCls = (active: boolean) =>
    `flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all ${
      active
        ? "text-[var(--primary)]"
        : "text-[var(--on-surface-variant)] hover:text-[var(--on-surface)] hover:bg-surface-variant/10"
    }`;

  return (
    <aside
      className={`fixed left-0 top-0 z-20 flex h-full flex-col border-r bg-surface/30 py-container-padding backdrop-blur-xl transition-all duration-500 ${
        collapsed ? "w-[60px]" : "w-sidebar-width"
      }`}
      style={{ borderColor: "color-mix(in srgb, var(--outline-variant) 20%, transparent)" }}
    >
      {/* Logo(折叠时隐藏,与原版 toggleSidebar 隐藏 border-glow 一致) */}
      <div className="mb-8 px-4" style={{ borderBottom: "1px solid var(--line)", display: collapsed ? "none" : undefined }}>
        <h1 className="font-display-lg text-2xl tracking-tighter text-primary">AETHER CONSOLE</h1>
      </div>

      {/* 收纳按钮 */}
      <button
        onClick={onToggleCollapsed}
        className="absolute right-2 top-2 flex h-7 w-7 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-surface-variant/20"
        style={{ color: "var(--on-surface-variant)" }}
        title="收起/展开导航"
      >
        <span className="material-symbols-outlined text-[16px]">menu</span>
      </button>

      <nav className="flex-1 space-y-1 px-2" style={{ display: collapsed ? "none" : undefined }}>
        {/* Orchestration */}
        <a
          onClick={() => onSwitchView("chat")}
          className={navItemCls(activeView === "chat")}
          style={
            activeView === "chat"
              ? { borderLeft: "4px solid var(--primary)", background: "var(--primary-faint)" }
              : { borderLeft: "4px solid transparent" }
          }
        >
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>
            hub
          </span>
          {!collapsed && <span className="font-headline-sm text-sm">Orchestration</span>}
        </a>

        {/* Agents 父级 */}
        <div>
          <a
            onClick={() => {
              onSwitchView("agents");
              setAgentsOpen(!agentsOpen);
            }}
            className="flex items-center justify-between gap-3 px-3 py-2.5 text-on-surface-variant hover:bg-surface-variant/10 hover:text-on-surface"
          >
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined">smart_toy</span>
              {!collapsed && <span className="font-headline-sm text-sm">Agents</span>}
            </div>
            {!collapsed && (
              <span
                className="material-symbols-outlined text-[15px] transition-transform duration-200"
                style={{ transform: agentsOpen ? "rotate(180deg)" : "" }}
              >
                expand_more
              </span>
            )}
          </a>

          {!collapsed && agentsOpen && (
            <div className="ml-3 mt-1 space-y-0.5">
              {/* Cloud Agents */}
              <div>
                <div
                  onClick={() => setCloudOpen(!cloudOpen)}
                  className="flex items-center justify-center gap-2 rounded-md px-3 py-2 text-on-surface-variant hover:bg-surface-variant/10"
                >
                  <span className="flex items-center gap-2 font-code-sm text-code-sm uppercase tracking-wider">
                    <span className="material-symbols-outlined text-[15px]">cloud</span>
                    Cloud Agents
                  </span>
                  <span className="ml-2 flex items-center gap-1">
                    <span className="rounded bg-surface-container-high px-1.5 text-[10px] text-on-surface">
                      {cloudAgents.length}
                    </span>
                    <span className="material-symbols-outlined text-[15px]">expand_more</span>
                  </span>
                </div>
                {cloudOpen && (
                  <div className="mt-1 space-y-1.5">
                    {cloudAgents.length === 0 ? (
                      <div className="px-3 py-1 text-xs text-on-surface-variant/50">无云端 Agent</div>
                    ) : (
                      cloudAgents.map((a) => (
                        <div
                          key={a.name}
                          className="glass-accent flex items-center gap-2.5 rounded-lg px-3 py-2"
                          style={{ ["--accent" as string]: "var(--tertiary)" }}
                        >
                          <StatusDot status={a.status} />
                          <span className="font-body-md text-[13px]" style={{ color: "var(--on-surface)" }}>
                            {a.name}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
              {/* Local Agents */}
              <div>
                <div
                  onClick={() => setLocalOpen(!localOpen)}
                  className="flex items-center justify-center gap-2 rounded-md px-3 py-2 text-on-surface-variant hover:bg-surface-variant/10"
                >
                  <span className="flex items-center gap-2 font-code-sm text-code-sm uppercase tracking-wider">
                    <span className="material-symbols-outlined text-[15px]">dns</span>
                    Local Agents
                  </span>
                  <span className="ml-2 flex items-center gap-1">
                    <span className="rounded bg-surface-container-high px-1.5 text-[10px] text-on-surface">
                      {localAgents.length}
                    </span>
                    <span className="material-symbols-outlined text-[15px]">expand_more</span>
                  </span>
                </div>
                {localOpen && (
                  <div className="mt-1 space-y-1.5">
                    {localAgents.length === 0 ? (
                      <div className="px-3 py-1 text-xs text-on-surface-variant/50">无本地 Agent</div>
                    ) : (
                      localAgents.map((a) => (
                        <div
                          key={a.name}
                          className="glass-accent flex items-center gap-2.5 rounded-lg px-3 py-2"
                          style={{ ["--accent" as string]: "var(--tertiary)" }}
                        >
                          <StatusDot status={a.status} />
                          <span className="font-body-md text-[13px]" style={{ color: "var(--on-surface)" }}>
                            {a.name}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Team */}
        <a
          onClick={() => onSwitchView("team")}
          className={navItemCls(activeView === "team")}
          style={
            activeView === "team"
              ? { borderLeft: "4px solid var(--primary)", background: "var(--primary-faint)" }
              : { borderLeft: "4px solid transparent" }
          }
        >
          <span className="material-symbols-outlined">groups</span>
          {!collapsed && <span className="font-headline-sm text-sm">Team</span>}
        </a>

        {/* History */}
        <a
          onClick={() => onSwitchView("history")}
          className={navItemCls(activeView === "history")}
          style={{ borderLeft: "4px solid transparent" }}
        >
          <span className="material-symbols-outlined">history</span>
          {!collapsed && <span className="font-headline-sm text-sm">History</span>}
        </a>
      </nav>

      {/* Sidebar Bottom: User + Settings(折叠时隐藏) */}
      <div className="relative mt-auto px-3 py-3" style={{ display: collapsed ? "none" : undefined }}>
        <button
          onClick={() => setUserMenuOpen(!userMenuOpen)}
          className="flex w-full cursor-pointer items-center gap-3 rounded-lg py-1.5 transition-colors hover:bg-surface-variant/10"
          title="用户"
        >
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            style={{ background: "var(--primary-faint)", border: "1px solid var(--primary)" }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
          </div>
          {!collapsed && (
            <>
              <span className="truncate text-xs text-on-surface-variant">User</span>
              <span
                className="material-symbols-outlined ml-auto text-[14px] text-on-surface-variant transition-transform"
                style={{ transform: userMenuOpen ? "rotate(180deg)" : "" }}
              >
                expand_less
              </span>
            </>
          )}
        </button>

        {/* 用户 popover */}
        {userMenuOpen && (
          <div
            ref={userMenuRef}
            className="glass-panel absolute bottom-full left-2 z-30 mb-2 w-56 animate-in overflow-hidden rounded-xl"
            style={{ boxShadow: "0 8px 30px rgba(0,0,0,0.35)" }}
          >
            <div className="border-b p-3" style={{ borderColor: "var(--border)" }}>
              <div className="flex items-center gap-3">
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-full"
                  style={{ background: "var(--primary-faint)", border: "1px solid var(--primary)" }}
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                  </svg>
                </div>
                <div>
                  <div className="text-sm font-medium text-on-surface">User</div>
                  <div className="text-xs text-on-surface-variant">本地组长实例</div>
                </div>
              </div>
            </div>
            <button
              onClick={onOpenSettings}
              className="flex w-full cursor-pointer items-center gap-2 px-4 py-2.5 text-left text-sm text-on-surface-variant transition-colors hover:bg-surface-variant/10"
            >
              <span className="material-symbols-outlined text-[16px]">settings</span>
              设置
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
