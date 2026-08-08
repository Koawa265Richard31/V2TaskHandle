"use client";

// 右侧编排 DAG 面板
import type { SubTask } from "@/hooks/useChat";
import { statusColor } from "@/hooks/useChat";

interface DagPanelProps {
  plan: SubTask[];
  collapsed?: boolean;
  onToggle?: () => void;
}

function TaskCard({ task }: { task: SubTask }) {
  const borderColor =
    task.status === "completed"
      ? "#34d399"
      : task.status === "running"
        ? "#f59e0b"
        : task.status === "failed" || task.status === "waiting_approval"
          ? "#f87171"
          : "#2a3040";
  const deps =
    task.dependencies && task.dependencies.length
      ? `deps: ${task.dependencies.join(",")}`
      : "";

  return (
    <div
      className="glass-accent animated-content rounded-lg border-l-4 p-3"
      style={{ ["--accent" as string]: "var(--tertiary)", borderLeftColor: borderColor }}
    >
      <div className="mb-1 flex items-start justify-between">
        <span className="font-code-sm text-code-sm text-on-surface">
          {task.description.slice(0, 40)}
        </span>
        <span className="rounded bg-surface-variant px-1 font-code-sm text-[10px] text-on-surface">
          {task.task_id}
        </span>
      </div>
      <div className="flex items-center justify-end gap-2">
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: statusColor(task.status) }} />
        <span className="font-code-sm text-[10px] text-on-surface-variant">{task.status}</span>
      </div>
      {deps && <div className="font-code-sm text-[10px] text-on-surface-variant">{deps}</div>}
    </div>
  );
}

export default function DagPanel({ plan, collapsed = false, onToggle }: DagPanelProps) {
  return (
    <aside
      className="glass-panel relative flex h-full flex-col overflow-hidden border-l transition-all duration-300"
      style={{
        width: collapsed ? 0 : 440,
        minWidth: collapsed ? 0 : 440,
        borderColor: "color-mix(in srgb, var(--outline-variant) 20%, transparent)",
        backgroundColor: "var(--surface-dim)",
        borderLeft: collapsed ? "none" : undefined,
      }}
    >
      <div className="relative z-10 flex items-center justify-between border-b bg-surface/40 p-4 backdrop-blur-sm" style={{ borderColor: "color-mix(in srgb, var(--outline-variant) 20%, transparent)" }}>
        <h2 className="font-headline-sm text-headline-sm text-on-surface">Orchestration Graph</h2>
        <div className="flex gap-2">
          <span className="material-symbols-outlined cursor-pointer text-sm text-on-surface-variant hover:text-primary">zoom_in</span>
          <span className="material-symbols-outlined cursor-pointer text-sm text-on-surface-variant hover:text-primary">zoom_out</span>
          {onToggle && (
            <button
              onClick={onToggle}
              className="flex h-6 w-6 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-surface-variant/20"
              title="收起/展开 DAG"
            >
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant">
                {collapsed ? "chevron_left" : "chevron_right"}
              </span>
            </button>
          )}
        </div>
      </div>
      {!collapsed && (
        <div className="relative z-10 flex flex-1 flex-col items-center overflow-auto p-4 scrollbar-thin">
          <div className="w-full space-y-3">
            {plan.map((t) => (
              <TaskCard key={t.task_id} task={t} />
            ))}
          </div>
          {plan.length === 0 && (
            <div className="py-10 text-center text-sm text-on-surface-variant">
              提交复杂任务后,这里展示分解的任务 DAG
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
