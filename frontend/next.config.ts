import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  // 仅 Electron 静态导出构建时用相对路径(file:// 下资源可加载);
  // dev / 普通 build 不加,避免相对路径破坏模块加载
  ...(process.env.NEXT_EXPORT ? { assetPrefix: "./" } : {}),
};

export default nextConfig;
