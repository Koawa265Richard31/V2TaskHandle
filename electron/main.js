// Electron 主进程:创建窗口 + 加载前端静态产物 + 管理本地后端子进程
const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const { BackendManager } = require("./backend");

const backend = new BackendManager();

// 前端产物路径:打包后优先 resources/frontend/out,开发时用项目 frontend/out
function frontendIndex() {
  const res = typeof process.resourcesPath !== "undefined" ? process.resourcesPath : null;
  const candidates = [
    res ? path.join(res, "frontend", "out", "index.html") : null,
    path.join(__dirname, "..", "frontend", "out", "index.html"),
  ].filter(Boolean);
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0];
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: "#121318",
    title: "Task Orchestrator",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const idx = frontendIndex();
  if (fs.existsSync(idx)) {
    win.loadFile(idx);
  } else {
    win.loadURL("http://localhost:3000");
  }

  return win;
}

// 后端状态广播
function broadcastStatus() {
  const status = {
    running: backend.isRunning(),
    role: backend.role,
    port: backend.port(),
  };
  for (const w of BrowserWindow.getAllWindows()) {
    w.webContents.send("backend:status-changed", status);
  }
}

// IPC:后端状态 / 切换角色 / 日志
ipcMain.handle("backend:status", () => ({
  running: backend.isRunning(),
  role: backend.role,
  port: backend.port(),
}));

ipcMain.handle("backend:switch-role", async (_e, role) => {
  if (role !== "leader" && role !== "member") return { ok: false, error: "无效角色" };
  const ok = await backend.start(role);
  broadcastStatus();
  return { ok, role, port: backend.port() };
});

ipcMain.handle("backend:logs", () => backend.logLines);

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// 退出时清理后端子进程
app.on("before-quit", () => {
  backend.stop();
});

app.on("window-all-closed", () => {
  backend.stop();
  if (process.platform !== "darwin") app.quit();
});

// 启动时自动拉起后端(默认组长角色,可用命令行 --role=leader|member 覆盖)
app.whenReady().then(async () => {
  const argRole = process.argv.find((a) => a.startsWith("--role="));
  const role = argRole ? argRole.split("=")[1] : process.env.PTA_DEFAULT_ROLE || "leader";
  await backend.start(role);
  broadcastStatus();
});
