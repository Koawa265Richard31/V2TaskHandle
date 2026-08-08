"use client";

// 顶部栏
interface HeaderProps {
  onToggleTheme: () => void;
  collapsed?: boolean;
}

export default function Header({ onToggleTheme, collapsed = false }: HeaderProps) {
  return (
    <header
      className="fixed right-0 top-0 z-20 flex h-16 items-center justify-between border-b bg-surface/10 px-container-padding backdrop-blur-md transition-all duration-300"
      style={{ width: `calc(100% - ${collapsed ? 60 : 260}px)`, borderColor: "var(--line)" }}
    >
      <div className="flex items-center gap-4">
        <span className="material-symbols-outlined text-on-surface-variant">menu</span>
        <span className="font-headline-sm text-sm text-on-surface">Agent Orchestrator</span>
      </div>
      <button
        onClick={onToggleTheme}
        className="cursor-pointer rounded-lg p-1.5 transition-colors hover:bg-surface-variant/20"
        title="切换主题"
      >
        <span className="material-symbols-outlined text-on-surface-variant">dark_mode</span>
      </button>
    </header>
  );
}
