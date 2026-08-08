import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  // 静态导出到 file://(Electron loadFile)时,资源须用相对路径
  assetPrefix: "./",
};

export default nextConfig;
