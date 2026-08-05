import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Task Orchestrator",
  description: "多 Agent 复杂任务编排系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full">
      <body className="h-full flex flex-col bg-[#0a0a0f] text-[#e4e4ec] font-sans">
        {children}
      </body>
    </html>
  );
}
