"use client";

// Agent Registry 视图 + codex 运行时配置
import { useState } from "react";
import type { AgentInfo } from "@/hooks/useAgents";
import { useCodexConfig } from "@/hooks/useCodexConfig";

interface AgentsViewProps {
  agents: AgentInfo[];
  loading: boolean;
  onRefresh: () => void;
}

function AgentRow({ agent }: { agent: AgentInfo }) {
  const status = agent.status || (agent.available ? "online" : "offline");
  const color =
    status === "online" ? "#34d399" : status === "busy" ? "#f59e0b" : "#908fa0";
  return (
    <div className="glass-panel flex items-center justify-between rounded-lg p-4">
      <div className="flex items-center gap-3">
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        <div>
          <div className="font-headline-sm text-headline-sm text-on-surface">{agent.name}</div>
          <div className="font-code-sm text-code-sm text-on-surface-variant">{agent.type}</div>
        </div>
      </div>
      <div className="text-right">
        <div className="font-code-sm text-[10px] uppercase text-on-surface-variant" style={{ color }}>
          {status}
        </div>
        <div className="font-code-sm text-[10px] text-on-surface-variant">
          {agent.available ? "available" : "offline"}
        </div>
      </div>
    </div>
  );
}

export default function AgentsView({ agents, loading, onRefresh }: AgentsViewProps) {
  const codex = useCodexConfig();
  const [cmdInput, setCmdInput] = useState("");
  const [homeInput, setHomeInput] = useState("");

  // 加载后填充表单
  const [inited, setInited] = useState(false);
  if (!inited && codex.config && (codex.config.codex_cmd || codex.config.codex_home)) {
    setCmdInput(codex.config.codex_cmd);
    setHomeInput(codex.config.codex_home);
    setInited(true);
  }

  const handleSave = async () => {
    const ok = await codex.save(cmdInput, homeInput);
    if (ok) onRefresh();
  };

  return (
    <div className="relative flex-1 flex-col overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-headline-md text-headline-md text-on-surface">Agent Registry</h2>
          <button
            onClick={onRefresh}
            className="cursor-pointer rounded-lg px-3 py-1.5 text-xs text-on-surface-variant transition-colors hover:bg-surface-variant/10"
          >
            刷新
          </button>
        </div>

        {/* Codex 运行时配置 */}
        <div className="glass-panel mb-6 rounded-lg p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="font-code-sm text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
              Codex 运行时配置
            </div>
            <span className="font-code-sm text-[10px] text-on-surface-variant">
              来源: {codex.config.source === "runtime" ? "界面配置" : ".env 默认"}
            </span>
          </div>
          <div className="space-y-3">
            <div>
              <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                codex 可执行文件路径
              </label>
              <input
                value={cmdInput}
                onChange={(e) => setCmdInput(e.target.value)}
                placeholder="如 C:\Users\...\OpenAI\Codex\bin\<hash>\codex.exe(留空自动发现)"
                className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
              />
            </div>
            <div>
              <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                CODEX_HOME(配置/认证目录)
              </label>
              <input
                value={homeInput}
                onChange={(e) => setHomeInput(e.target.value)}
                placeholder="如 D:\software\codex-cli\codex-cli-data(留空用默认)"
                className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => codex.verify(cmdInput, homeInput)}
                disabled={codex.loading}
                className="cursor-pointer rounded-md border px-3 py-1.5 text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
                style={{ borderColor: "var(--border)", color: "var(--on-surface-variant)" }}
              >
                验证
              </button>
              <button
                onClick={handleSave}
                disabled={codex.saving || codex.loading}
                className="cursor-pointer rounded-md px-3 py-1.5 text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                style={{ backgroundColor: "var(--primary)", color: "var(--on-primary)" }}
              >
                {codex.saving ? "保存中…" : "保存"}
              </button>
              {codex.message && (
                <span
                  className="font-code-sm text-[11px]"
                  style={{ color: codex.verifyResult?.available || codex.message === "已保存" ? "#34d399" : "var(--on-surface-variant)" }}
                >
                  {codex.message}
                </span>
              )}
            </div>
          </div>
        </div>

        {loading ? (
          <div className="py-10 text-center text-sm text-on-surface-variant">加载中…</div>
        ) : agents.length === 0 ? (
          <div className="py-10 text-center text-sm text-on-surface-variant">暂无 Agent</div>
        ) : (
          <div className="space-y-3">
            {agents.map((a) => (
              <AgentRow key={a.name} agent={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
