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
import { useChat } from "@/hooks/useChat";
import { useAgents } from "@/hooks/useAgents";
import { useRegistry } from "@/hooks/useRegistry";
import { useExternalAgents } from "@/hooks/useExternalAgents";
import TeamPanel from "@/components/TeamPanel";

export default function HomePage() {
  const { messages, plan, streaming, error, sendMessage, newSession } = useChat();
  const { agents, cloudAgents, localAgents, loading, refresh } = useAgents();
  const registry = useRegistry();
  const extAgents = useExternalAgents();
  const [activeView, setActiveView] = useState("chat");
  const [theme, setThemeState] = useState<string>("dark");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [dagCollapsed, setDagCollapsed] = useState(false);
  const mainOffset = collapsed ? 60 : 260;

  // 初始化主题
  useEffect(() => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme") || "dark";
    setThemeState(cur);
    root.classList.toggle("dark", cur === "dark");
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

      <Sidebar
        agents={agents}
        cloudAgents={cloudAgents}
        localAgents={localAgents}
        activeView={activeView}
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed(!collapsed)}
        onSwitchView={handleSwitchView}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <Header onToggleTheme={toggleTheme} collapsed={collapsed} />

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
            onApprove={registry.approve}
            onJoin={registry.join}
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
