"use client";

// POC:React 版 Aether Console(与 console.html 对照)
import { useCallback, useEffect, useState } from "react";
import GradientWaves from "@/components/GradientWaves";
import Sidebar from "@/components/Sidebar";
import Header from "@/components/Header";
import ChatView from "@/components/ChatView";
import AgentsView from "@/components/AgentsView";
import DagPanel from "@/components/DagPanel";
import SettingsDrawer from "@/components/SettingsDrawer";
import IdentityModal from "@/components/IdentityModal";
import { useChat } from "@/hooks/useChat";
import { useAgents } from "@/hooks/useAgents";
import { useRegistry } from "@/hooks/useRegistry";
import { useExternalAgents } from "@/hooks/useExternalAgents";
import TeamPanel from "@/components/TeamPanel";

const IDENTITY_KEY = "task_orchestrator_identity";

interface Identity {
  name: string;
  role: "leader" | "member";
}

function loadIdentity(): Identity | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(IDENTITY_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return null;
}

function saveIdentity(ident: Identity) {
  localStorage.setItem(IDENTITY_KEY, JSON.stringify(ident));
}

export default function HomePage() {
  const { messages, plan, streaming, error, sendMessage, newSession } = useChat();
  const { agents, cloudAgents, localAgents, loading, refresh } = useAgents();
  const registry = useRegistry();
  const extAgents = useExternalAgents();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [showIdentityModal, setShowIdentityModal] = useState(false);
  const [activeView, setActiveView] = useState("chat");
  const [theme, setThemeState] = useState<string>("dark");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [dagCollapsed, setDagCollapsed] = useState(false);
  const mainOffset = collapsed ? 60 : 260;

  // 加载身份:localStorage → 无则弹模态框
  useEffect(() => {
    const stored = loadIdentity();
    if (stored && stored.name) {
      setIdentity(stored);
      // 同步后端
      fetch("/api/identity", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(stored),
      }).catch(() => {});
    } else {
      setShowIdentityModal(true);
    }
  }, []);

  // 初始化主题
  useEffect(() => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme") || "dark";
    setThemeState(cur);
    root.classList.toggle("dark", cur === "dark");
  }, []);

  const handleIdentityConfirm = useCallback(async (ident: Identity) => {
    saveIdentity(ident);
    setIdentity(ident);
    setShowIdentityModal(false);
    try {
      const r = await fetch("/api/identity", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ident),
      });
      const data = await r.json();
      if (data.role_changed) {
        // 角色变了需要通知 Electron 重启后端
        if ((window as any).__switchRole) {
          (window as any).__switchRole?.(ident.role);
        }
      }
    } catch { /* ignore */ }
    // 刷新 registry hook 的状态
    window.location.reload();
  }, []);

  const setTheme = useCallback((t: string) => {
    const root = document.documentElement;
    root.setAttribute("data-theme", t);
    root.classList.toggle("dark", t === "dark");
    setThemeState(t);
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "light" ? "dark" : "light");
  }, [theme, setTheme]);

  const handleSwitchView = useCallback((view: string) => {
    setActiveView(view);
  }, []);

  return (
    <>
      <GradientWaves />
      <div className="bg-ripple" />

      {showIdentityModal && (
        <IdentityModal
          initial={{ name: identity?.name || "", role: identity?.role || "leader" }}
          onConfirm={handleIdentityConfirm}
        />
      )}

      <Sidebar
        agents={agents}
        cloudAgents={cloudAgents}
        localAgents={localAgents}
        activeView={activeView}
        collapsed={collapsed}
        identity={identity}
        onToggleCollapsed={() => setCollapsed(!collapsed)}
        onSwitchView={handleSwitchView}
        onOpenSettings={() => setSettingsOpen(true)}
        onSwitchIdentity={() => setShowIdentityModal(true)}
      />

      <Header
        identity={identity}
        onToggleTheme={toggleTheme}
        collapsed={collapsed}
        onSwitchIdentity={() => setShowIdentityModal(true)}
      />

      <main
        className="relative z-10 flex h-[calc(100vh-64px)]"
        style={{ marginLeft: `${mainOffset}px` }}
      >
        {activeView === "chat" && (
          <ChatView messages={messages} streaming={streaming} onSend={sendMessage} onNewSession={newSession} />
        )}
        {activeView === "agents" && (
          <AgentsView
            agents={agents}
            loading={loading}
            onRefresh={refresh}
            externalAgents={{
              extAgents: extAgents.agents,
              extLoading: extAgents.loading,
              extSaving: extAgents.saving,
              extVerifyResult: extAgents.verifyResult,
              extMessage: extAgents.message,
              onExtRegister: extAgents.register,
              onExtRemove: extAgents.remove,
              onExtVerify: extAgents.verify,
            }}
          />
        )}
        {activeView === "history" && (
          <div className="flex flex-1 flex-col items-center justify-center p-6">
            <h2 className="font-headline-md text-headline-md text-on-surface">History</h2>
            <p className="mt-2 text-sm text-on-surface-variant">会话历史(待实现)</p>
          </div>
        )}
        {activeView === "team" && (
          <TeamPanel
            status={registry.status}
            loading={registry.loading}
            inviteCode={registry.inviteCode}
            inviteCodeLoading={registry.inviteCodeLoading}
            onApprove={registry.approve}
            onJoin={registry.join}
            onJoinByCode={registry.joinByCode}
            onFetchInviteCode={registry.fetchInviteCode}
            onRegenerateInviteCode={registry.regenerateInviteCode}
          />
        )}

        {activeView === "chat" && (
          <DagPanel
            plan={plan}
            collapsed={dagCollapsed}
            onToggle={() => setDagCollapsed(!dagCollapsed)}
          />
        )}
      </main>

      <SettingsDrawer
        open={settingsOpen}
        theme={theme}
        onSetTheme={setTheme}
        onClose={() => setSettingsOpen(false)}
      />

      {error && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-error/90 px-4 py-2 text-sm text-on-error">
          {error}
        </div>
      )}
    </>
  );
}
