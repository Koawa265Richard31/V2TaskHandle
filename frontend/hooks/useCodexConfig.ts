"use client";

// codex 运行时配置 hook:加载/保存/验证 codex 路径与 CODEX_HOME
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

const API_URL = getApiBase();

export interface CodexConfig {
  codex_cmd: string;
  codex_home: string;
  source?: string;
}

export function useCodexConfig() {
  const [config, setConfig] = useState<CodexConfig>({ codex_cmd: "", codex_home: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; available: boolean; codex_cmd?: string } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/config/codex`);
      if (r.ok) {
        const data = (await r.json()) as CodexConfig;
        setConfig(data);
      }
    } catch {
      // 后端不可达
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = useCallback(
    async (cmd: string, home: string) => {
      setSaving(true);
      setMessage(null);
      try {
        const r = await fetch(`${API_URL}/api/config/codex`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ codex_cmd: cmd, codex_home: home }),
        });
        const data = await r.json();
        if (data.ok) {
          setConfig({ codex_cmd: data.codex_cmd, codex_home: data.codex_home, source: "runtime" });
          setMessage("已保存");
        } else {
          setMessage(data.error || "保存失败");
        }
        return data.ok as boolean;
      } catch (e) {
        setMessage(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const verify = useCallback(async (cmd: string, home: string) => {
    setVerifyResult(null);
    setMessage(null);
    try {
      const r = await fetch(`${API_URL}/api/config/codex/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codex_cmd: cmd, codex_home: home }),
      });
      const data = await r.json();
      setVerifyResult(data);
      setMessage(data.available ? "路径可用" : "路径不可用,请检查");
      return data.available as boolean;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
      return false;
    }
  }, []);

  return { config, loading, saving, verifyResult, message, save, verify, reload: load };
}
