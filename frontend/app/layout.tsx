import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AETHER CONSOLE",
  description: "多 Agent 复杂任务编排系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full dark" data-theme="dark">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Hanken+Grotesk:wght@600;700&family=JetBrains+Mono:wght@500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="h-full overflow-hidden font-sans">
        {children}
      </body>
    </html>
  );
}
