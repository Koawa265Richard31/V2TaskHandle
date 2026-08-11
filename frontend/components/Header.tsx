"use client";

// 顶部栏:显示角色标签 + 用户名 + 身份切换
interface Identity {
  name: string;
  role: "leader" | "member";
}

interface HeaderProps {
  identity: Identity | null;
  onToggleTheme: () => void;
  collapsed?: boolean;
  onSwitchIdentity?: () => void;
}

export default function Header({ identity, onToggleTheme, collapsed = false, onSwitchIdentity }: HeaderProps) {
  return (
    <header
      className="fixed right-0 top-0 z-20 flex h-16 items-center justify-between border-b bg-surface/10 px-container-padding backdrop-blur-md transition-all duration-300"
      style={{ width: `calc(100% - ${collapsed ? 60 : 260}px)`, borderColor: "var(--line)" }}
    >
      <div className="flex items-center gap-4">
        {identity && (
          <span
            className="rounded-full px-2.5 py-0.5 text-[11px] font-medium"
            style={{
              backgroundColor: identity.role === "leader" ? "var(--primary-faint)" : "var(--tertiary-container)",
              color: identity.role === "leader" ? "var(--primary)" : "var(--on-tertiary-container)",
            }}
          >
            {identity.role === "leader" ? "组长" : "组员"}
          </span>
        )}
        <span className="font-headline-sm text-sm text-on-surface">
          {identity ? `${identity.name}` : "Agent Orchestrator"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {onSwitchIdentity && (
          <button
            onClick={onSwitchIdentity}
            className="cursor-pointer rounded-lg p-1.5 text-xs text-on-surface-variant transition-colors hover:bg-surface-variant/20"
            title="切换身份"
          >
            切换身份
          </button>
        )}
        <button
          onClick={onToggleTheme}
          className="cursor-pointer rounded-lg p-1.5 transition-colors hover:bg-surface-variant/20"
          title="切换主题"
        >
          <span className="material-symbols-outlined text-on-surface-variant">dark_mode</span>
        </button>
      </div>
    </header>
  );
}
