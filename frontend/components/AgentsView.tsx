"use client";

// Agent Registry 视图
import type { AgentInfo } from "@/hooks/useAgents";

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
