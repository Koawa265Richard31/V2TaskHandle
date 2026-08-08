"use client";

// 设置抽屉:主题切换
interface SettingsDrawerProps {
  open: boolean;
  theme: string;
  onSetTheme: (t: string) => void;
  onClose: () => void;
}

export default function SettingsDrawer({ open, theme, onSetTheme, onClose }: SettingsDrawerProps) {
  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onClose}
      />
      <div
        className={`glass-panel fixed right-0 top-0 z-50 h-full w-[360px] transform transition-transform duration-300 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
        style={{ backdropFilter: "blur(20px)" }}
      >
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--border)" }}>
          <span className="font-code-sm text-code-sm uppercase tracking-wider text-on-surface-variant">Settings</span>
          <button
            onClick={onClose}
            className="cursor-pointer rounded-lg p-1.5 text-on-surface-variant transition-colors hover:bg-surface-variant/20"
          >
            ✕
          </button>
        </div>
        <div className="space-y-5 p-5">
          <div>
            <div className="mb-2 text-sm font-medium text-on-surface">Theme</div>
            <div className="flex gap-2">
              <button
                onClick={() => onSetTheme("dark")}
                className="flex-1 cursor-pointer rounded-lg border px-4 py-2.5 text-sm transition-colors"
                style={{ borderColor: theme === "dark" ? "var(--primary)" : "var(--border)" }}
              >
                <span className="block text-on-surface">Dark</span>
                <span className="mt-0.5 block text-xs text-on-surface-variant">黑紫</span>
              </button>
              <button
                onClick={() => onSetTheme("light")}
                className="flex-1 cursor-pointer rounded-lg border px-4 py-2.5 text-sm transition-colors"
                style={{ borderColor: theme === "light" ? "var(--primary)" : "var(--border)" }}
              >
                <span className="block text-on-surface">Light</span>
                <span className="mt-0.5 block text-xs text-on-surface-variant">蓝白</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
