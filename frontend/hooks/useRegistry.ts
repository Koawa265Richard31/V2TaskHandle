"use client";

// 注册中心状态 hook:15s 轮询 /api/peers + approve/join 操作
import { useCallback, useEffect, useState } from "react";
import { getApiBase } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface PeerInfo {
  request_id?: number;
  peer_id: number;
  name: string;
  url: string;
}

export interface RegistryRequest {
  id: number;
  peer_id: number;
  peer_name: string;
  peer_url: string;
  leader_id: number;
  status: string;
  created_at: number;
  decided_at?: number | null;
}

export interface RegistryStatus {
  registered: boolean;
  peer_id: number | null;
  role: string;
  name: string;
  registry_url: string;
  approved_peers: PeerInfo[];
  requests: RegistryRequest[];
}

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

  const approve = useCallback(
    async (requestId: number, ok: boolean): Promise<boolean> => {
      try {
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
      } catch {
        return false;
      }
    },
    [refresh],
  );

  const join = useCallback(
    async (leaderId: number): Promise<{ ok: boolean; error?: string }> => {
      try {
        const r = await fetch(`${API_URL}/api/join-request`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ leader_id: leaderId }),
        });
        const data = await r.json();
        await refresh();
        return data;
      } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : String(e) };
      }
    },
    [refresh],
  );

  return { status, loading, refresh, approve, join };
}
