"use client";

// 团队协作面板:注册状态 / 待批准申请(组长) / 已加入团队 / 申请状态(组员)
import { useState } from "react";
import type { RegistryStatus } from "@/hooks/useRegistry";

interface TeamPanelProps {
  status: RegistryStatus | null;
  loading: boolean;
  onApprove: (requestId: number, ok: boolean) => Promise<boolean>;
  onJoin: (leaderId: number) => Promise<{ ok: boolean; error?: string }>;
}

export default function TeamPanel({ status, loading, onApprove, onJoin }: TeamPanelProps) {
  const [leaderIdInput, setLeaderIdInput] = useState("");
  const [joinMsg, setJoinMsg] = useState<string | null>(null);

  const isLeader = status?.role === "leader";
  const registered = !!status?.registered;

  const handleJoin = async () => {
    const id = Number(leaderIdInput);
    if (!id || Number.isNaN(id)) {
      setJoinMsg("请输入有效的组长 ID");
      return;
    }
    setJoinMsg(null);
    const res = await onJoin(id);
    if (res.ok) {
      setJoinMsg("已发起加入申请");
    } else {
      setJoinMsg(res.error || "申请失败");
    }
  };

  return (
    <div className="relative flex-1 flex-col overflow-y-auto p-6">
      <div className="mx-auto w-full max-w-2xl">
        <h2 className="font-headline-md mb-4 text-headline-md text-on-surface">团队协作</h2>

        {/* 注册状态 */}
        <div className="glass-panel mb-4 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${registered ? "agent-live-dot" : ""}`}
              style={{ backgroundColor: registered ? "#34d399" : "#908fa0" }}
            />
            {registered ? (
              <span className="font-body-md text-body-md text-on-surface">
                已注册 (ID: {status?.peer_id})
              </span>
            ) : (
              <span className="font-body-md text-body-md text-on-surface-variant">
                未注册到注册中心
              </span>
            )}
          </div>
          <div className="font-code-sm mt-1 text-code-sm text-on-surface-variant">
            角色: {isLeader ? "组长" : "组员"}
            {status?.registry_url ? ` · 注册中心: ${status.registry_url}` : ""}
          </div>
        </div>

        {loading && (
          <div className="py-4 text-center text-sm text-on-surface-variant">加载中…</div>
        )}

        {/* 组长视角:待批准申请 */}
        {isLeader && (
          <div className="glass-panel mb-4 rounded-lg p-4">
            <div className="font-code-sm mb-2 text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
              待批准申请
            </div>
            {!status?.requests?.length ? (
              <div className="text-xs text-on-surface-variant/60">暂无待批准申请</div>
            ) : (
              status.requests.map((r) => (
                <div
                  key={r.id}
                  className="mb-2 rounded-lg p-2.5 text-xs"
                  style={{ backgroundColor: "var(--surface-container-low)", border: "1px solid var(--border)" }}
                >
                  <div className="font-medium text-on-surface">{r.peer_name}</div>
                  <div className="font-code-sm mt-0.5 text-on-surface-variant">{r.peer_url}</div>
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => onApprove(r.id, true)}
                      className="cursor-pointer rounded-md px-2.5 py-1 text-[11px] font-medium transition-opacity hover:opacity-80"
                      style={{ backgroundColor: "#34d399", color: "#000" }}
                    >
                      批准
                    </button>
                    <button
                      onClick={() => onApprove(r.id, false)}
                      className="cursor-pointer rounded-md border px-2.5 py-1 text-[11px] transition-opacity hover:opacity-80"
                      style={{ borderColor: "var(--error)", color: "var(--error)" }}
                    >
                      拒绝
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* 组长视角:已加入团队 */}
        {isLeader && (
          <div className="glass-panel mb-4 rounded-lg p-4">
            <div className="font-code-sm mb-2 text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
              已加入团队
            </div>
            {!status?.approved_peers?.length ? (
              <div className="text-xs text-on-surface-variant/60">暂无已批准的组员</div>
            ) : (
              status.approved_peers.map((p) => (
                <div key={p.peer_id} className="mb-1.5 flex items-center gap-2 text-xs">
                  <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#34d399" }} />
                  <span className="text-on-surface">{p.name}</span>
                  <span className="font-code-sm ml-auto truncate text-on-surface-variant">{p.url}</span>
                </div>
              ))
            )}
          </div>
        )}

        {/* 组员视角:申请状态 */}
        {!isLeader && (
          <div className="glass-panel rounded-lg p-4">
            <div className="font-code-sm mb-2 text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
              加入组长团队
            </div>
            {status?.registry_url ? (
              <>
                <div className="mb-2 flex gap-2">
                  <input
                    value={leaderIdInput}
                    onChange={(e) => setLeaderIdInput(e.target.value)}
                    placeholder="组长 ID"
                    type="number"
                    className="w-32 rounded-md border px-3 py-2 font-code-sm text-code-sm text-on-surface focus:ring-0"
                    style={{ backgroundColor: "var(--surface-container-low)", borderColor: "var(--border)" }}
                  />
                  <button
                    onClick={handleJoin}
                    className="cursor-pointer rounded-md px-3 py-2 text-xs font-medium transition-opacity hover:opacity-80"
                    style={{ backgroundColor: "var(--primary)", color: "var(--on-primary)" }}
                  >
                    发起申请
                  </button>
                </div>
                {joinMsg && <div className="text-xs text-on-surface-variant">{joinMsg}</div>}
              </>
            ) : (
              <div className="text-xs text-on-surface-variant/60">未配置注册中心 (PTA_REGISTRY_URL)</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
