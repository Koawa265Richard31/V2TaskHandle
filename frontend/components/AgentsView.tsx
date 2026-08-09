"use client";

// Agent Registry 视图 + codex 运行时配置 + 远程 Agent 注册
import { useState } from "react";
import type { AgentInfo } from "@/hooks/useAgents";
import { useCodexConfig } from "@/hooks/useCodexConfig";
import type { ExternalAgent, VerifyResult } from "@/hooks/useExternalAgents";

interface ExternalAgentsProps {
  extAgents: ExternalAgent[];
  extLoading: boolean;
  extSaving: boolean;
  extVerifyResult: VerifyResult | null;
  extMessage: string | null;
  onExtRegister: (name: string, baseUrl: string, apiKey: string, capability: string, agentType: string) => Promise<boolean>;
  onExtRemove: (name: string) => Promise<boolean>;
  onExtVerify: (name: string) => Promise<boolean>;
}


interface AgentsViewProps {
  agents: AgentInfo[];
  loading: boolean;
  onRefresh: () => void;
  externalAgents?: ExternalAgentsProps;
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

export default function AgentsView({ agents, loading, onRefresh, externalAgents }: AgentsViewProps) {
  const codex = useCodexConfig();
  const [cmdInput, setCmdInput] = useState("");
  const [homeInput, setHomeInput] = useState("");

  // 远程 Agent 注册表单状态
  const [extForm, setExtForm] = useState({
    name: "",
    baseUrl: "",
    apiKey: "",
    capability: "retrieve",
    agentType: "retrieval",
  });

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

  const ext = externalAgents;

  const handleExtRegister = async () => {
    if (!ext || !extForm.name.trim() || !extForm.baseUrl.trim()) return;
    const ok = await ext.onExtRegister(
      extForm.name.trim(), extForm.baseUrl.trim(), extForm.apiKey.trim(),
      extForm.capability.trim(), extForm.agentType,
    );
    if (ok) {
      setExtForm({ name: "", baseUrl: "", apiKey: "", capability: "retrieve", agentType: "retrieval" });
      onRefresh();
    }
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

        {/* 远程 Agent 注册 */}
        <div className="glass-panel mb-6 rounded-lg p-4">
          <div className="mb-3">
            <div className="font-code-sm text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
              远程 Agent 注册
            </div>
          </div>

          {/* 注册表单 */}
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                  名称
                </label>
                <input
                  value={extForm.name}
                  onChange={(e) => setExtForm({ ...extForm, name: e.target.value })}
                  placeholder="如 ragent"
                  className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                  style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
                />
              </div>
              <div>
                <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                  Agent 类型
                </label>
                <select
                  value={extForm.agentType}
                  onChange={(e) => setExtForm({ ...extForm, agentType: e.target.value })}
                  className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                  style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
                >
                  <option value="retrieval">REST (retrieval)</option>
                  <option value="mcp">MCP</option>
                </select>
              </div>
            </div>
            <div>
              <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                Base URL(如 http://localhost:9099/mcp)
              </label>
              <input
                value={extForm.baseUrl}
                onChange={(e) => setExtForm({ ...extForm, baseUrl: e.target.value })}
                placeholder="http://localhost:9099/mcp"
                className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                  API Key(可选)
                </label>
                <input
                  value={extForm.apiKey}
                  onChange={(e) => setExtForm({ ...extForm, apiKey: e.target.value })}
                  placeholder="Bearer token(可选)"
                  className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                  style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
                />
              </div>
              <div>
                <label className="font-code-sm mb-1 block text-[11px] text-on-surface-variant">
                  能力标签
                </label>
                <input
                  value={extForm.capability}
                  onChange={(e) => setExtForm({ ...extForm, capability: e.target.value })}
                  placeholder="如 retrieve, mcp"
                  className="w-full rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                  style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => extForm.name ? ext?.onExtVerify(extForm.name) : null}
                disabled={ext?.extSaving || !extForm.name.trim()}
                className="cursor-pointer rounded-md border px-3 py-1.5 text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
                style={{ borderColor: "var(--border)", color: "var(--on-surface-variant)" }}
              >
                验证
              </button>
              <button
                onClick={handleExtRegister}
                disabled={ext?.extSaving || !extForm.name.trim() || !extForm.baseUrl.trim()}
                className="cursor-pointer rounded-md px-3 py-1.5 text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                style={{ backgroundColor: "var(--primary)", color: "var(--on-primary)" }}
              >
                {ext?.extSaving ? "注册中…" : "注册"}
              </button>
              {ext?.extMessage && (
                <span
                  className="font-code-sm text-[11px]"
                  style={{ color: ext.extVerifyResult?.available ? "#34d399" : "var(--on-surface-variant)" }}
                >
                  {ext.extMessage}
                </span>
              )}
            </div>
          </div>

          {/* 已注册的外部 Agent 列表 */}
          {ext && ext.extAgents.length > 0 && (
            <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--border)" }}>
              <div className="mb-2 font-code-sm text-[10px] uppercase tracking-wider text-on-surface-variant">
                已注册({ext.extAgents.length})
              </div>
              <div className="space-y-1.5">
                {ext.extAgents.map((a) => (
                  <div
                    key={a.name}
                    className="flex items-center justify-between rounded-md px-3 py-1.5"
                    style={{ backgroundColor: "var(--surface-container-low)" }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      <span className="font-code-sm text-[12px] text-on-surface">{a.name}</span>
                      <span className="font-code-sm text-[10px] text-on-surface-variant">
                        {a.agent_type} · {a.base_url}
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => ext.onExtVerify(a.name)}
                        className="cursor-pointer rounded px-1.5 py-0.5 text-[10px] text-on-surface-variant transition-colors hover:bg-surface-variant/10"
                        title="验证"
                      >
                        验证
                      </button>
                      <button
                        onClick={() => ext.onExtRemove(a.name)}
                        className="cursor-pointer rounded px-1.5 py-0.5 text-[10px] text-rose-400 transition-colors hover:bg-rose-400/10"
                        title="删除"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {ext?.extLoading && (
            <div className="mt-2 text-center text-xs text-on-surface-variant">加载中…</div>
          )}
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
