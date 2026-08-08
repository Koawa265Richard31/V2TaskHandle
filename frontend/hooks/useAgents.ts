"use client";

// Agent 列表 hook:迁移自 console.html 的 loadAgents/loadAgentsList 逻辑
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

export interface AgentInfo {
  name: string;
  type: string;
  available: boolean;
  status?: string;
}

const API_URL = getApiBase();

export function useAgents() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/agents`);
      const data = (await r.json()) as AgentInfo[];
      setAgents(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const cloudAgents = agents.filter((a) => a.type === "a2a" || a.type === "retrieval");
  const localAgents = agents.filter(
    (a) => a.type === "codex" || a.type === "codex_cli" || a.type === "local",
  );

  return { agents, cloudAgents, localAgents, loading, error, refresh };
}
