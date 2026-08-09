"use client";

// 远程 Agent 运行时注册 hook:加载/注册/删除/验证外部 Agent
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

const API_URL = getApiBase();

export interface ExternalAgent {
  id: number;
  name: string;
  base_url: string;
  api_key: string;
  capability: string;
  agent_type: string;
  created_at: string;
}

export interface VerifyResult {
  ok: boolean;
  available: boolean;
  agent_type?: string;
  tools?: string[];
  error?: string;
}

export function useExternalAgents() {
  const [agents, setAgents] = useState<ExternalAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/external-agents`);
      const data = (await r.json()) as ExternalAgent[];
      setAgents(data);
    } catch {
      // 后端不可达
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const register = useCallback(
    async (
      name: string,
      baseUrl: string,
      apiKey: string,
      capability: string,
      agentType: string,
    ) => {
      setSaving(true);
      setMessage(null);
      try {
        const r = await fetch(`${API_URL}/api/external-agents`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            base_url: baseUrl,
            api_key: apiKey,
            capability,
            agent_type: agentType,
          }),
        });
        const data = await r.json();
        if (data.ok) {
          setMessage(`已注册: ${data.name}`);
          await load();
        } else {
          setMessage(data.error || "注册失败");
        }
        return data.ok as boolean;
      } catch (e) {
        setMessage(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setSaving(false);
      }
    },
    [load],
  );

  const remove = useCallback(
    async (name: string) => {
      setMessage(null);
      try {
        const r = await fetch(`${API_URL}/api/external-agents/${encodeURIComponent(name)}`, {
          method: "DELETE",
        });
        const data = await r.json();
        if (data.ok) {
          setMessage(`已删除: ${name}`);
          await load();
        } else {
          setMessage(data.error || "删除失败");
        }
        return data.ok as boolean;
      } catch (e) {
        setMessage(e instanceof Error ? e.message : String(e));
        return false;
      }
    },
    [load],
  );

  const verify = useCallback(async (name: string) => {
    setVerifyResult(null);
    setMessage(null);
    try {
      const r = await fetch(
        `${API_URL}/api/external-agents/${encodeURIComponent(name)}/verify`,
        { method: "POST" },
      );
      const data = (await r.json()) as VerifyResult;
      setVerifyResult(data);
      if (data.available) {
        const toolList = data.tools?.join(", ") || "无";
        setMessage(`连通成功 — 发现工具: ${toolList}`);
      } else {
        setMessage(data.error || "连通失败");
      }
      return data.available;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
      return false;
    }
  }, []);

  return { agents, loading, saving, verifyResult, message, load, register, remove, verify };
}
