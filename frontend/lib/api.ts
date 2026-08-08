"use client";

// 统一 API 基地址:优先运行时注入(Electron preload 设置 window.__API_BASE__),
// 其次 NEXT_PUBLIC_API_URL,最后默认本地后端。
declare global {
  interface Window {
    __API_BASE__?: string;
  }
}

export function getApiBase(): string {
  if (typeof window !== "undefined" && window.__API_BASE__) {
    return window.__API_BASE__.replace(/\/$/, "");
  }
  return (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export const API_URL = getApiBase();
