"use client";

import { useCallback, useEffect, useState } from "react";
import type { RegistryStatus } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useRegistry() {
  const [status, setStatus] = useState<RegistryStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/api/peers`);
      if (r.ok) {
        setStatus(await r.json());
      }
    } catch {
      // 后端不可达:保留上次状态
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 15000); // 每 15s 轮询注册状态
    return () => clearInterval(timer);
  }, [refresh]);

  const approve = useCallback(async (requestId: number, ok: boolean) => {
    const r = await fetch(`${API_URL}/api/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, approve: ok }),
    });
    if (r.ok) {
      await refresh();
      return true;
    }
    return false;
  }, [refresh]);

  const join = useCallback(async (leaderId: number) => {
    const r = await fetch(`${API_URL}/api/join-request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leader_id: leaderId }),
    });
    const data = await r.json();
    await refresh();
    return data;
  }, [refresh]);

  return { status, loading, refresh, approve, join };
}
