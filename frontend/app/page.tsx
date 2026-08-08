"use client";

import { useEffect } from "react";

export default function HomePage() {
  useEffect(() => {
    window.location.replace("/console.html");
  }, []);

  return (
    <div className="h-screen flex items-center justify-center" style={{ backgroundColor: "#121318" }}>
      <div style={{ color: "#e3e1e9", fontSize: 14 }}>正在加载控制台…</div>
    </div>
  );
}
