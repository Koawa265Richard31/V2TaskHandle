// 本地后端进程管理:按角色启动组长(8000)/组员(8101)后端子进程,退出时清理
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const PROJECT_ROOT = path.join(__dirname, "..");

// 找 python:优先 .venv,回退系统 python
function findPython() {
  const candidates = [
    path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe"),
    path.join(PROJECT_ROOT, ".venv", "bin", "python"),
    "python",
  ];
  for (const c of candidates) {
    if (c === "python") return c;
    if (fs.existsSync(c)) return c;
  }
  return "python";
}

const PYTHON = findPython();

// 环境变量:合并 .env(简单解析) + 角色相关配置
function loadEnv(role) {
  const env = { ...process.env };
  // 读 .env
  const envPath = path.join(PROJECT_ROOT, ".env");
  if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, "utf-8").split("\n");
    for (const line of lines) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m) env[m[1]] = m[2];
    }
  }
  // 角色配置
  if (role === "leader") {
    env.PTA_A2A_ROLE = "leader";
    env.PTA_API_PORT = process.env.PTA_API_PORT || "8000";
  } else {
    env.PTA_A2A_ROLE = "member";
    env.PTA_A2A_PORT = process.env.PTA_A2A_PORT || "8101";
  }
  // 注册中心默认本地
  env.PTA_REGISTRY_URL = env.PTA_REGISTRY_URL || process.env.PTA_REGISTRY_URL || "";
  return env;
}

class BackendManager {
  constructor() {
    this.proc = null;
    this.role = null;
    this.logLines = [];
  }

  isRunning() {
    return this.proc && !this.proc.killed;
  }

  port() {
    return this.role === "leader" ? Number(process.env.PTA_API_PORT || 8000) : Number(process.env.PTA_A2A_PORT || 8101);
  }

  // 启动后端:leader → uvicorn api.server(8000);member → task_orchestrator.cli(8101)
  async start(role) {
    if (this.isRunning()) {
      if (this.role === role) return true;
      this.stop();
    }
    this.role = role;
    const env = loadEnv(role);

    let cmd, args;
    if (role === "leader") {
      cmd = PYTHON;
      args = ["-m", "uvicorn", "task_orchestrator.api.server:app", "--host", "127.0.0.1", "--port", env.PTA_API_PORT || "8000"];
    } else {
      cmd = PYTHON;
      args = ["-m", "task_orchestrator.cli", "--role", "member", "--port", env.PTA_A2A_PORT || "8101"];
    }

    this.proc = spawn(cmd, args, {
      cwd: PROJECT_ROOT,
      env,
      windowsHide: true,
    });

    this.proc.stdout.on("data", (d) => this._log(d));
    this.proc.stderr.on("data", (d) => this._log(d));
    this.proc.on("exit", (code) => {
      this.logLines.push(`[backend exit] code=${code}`);
      this.proc = null;
    });

    // 等待端口就绪
    return this._waitReady(role);
  }

  _log(d) {
    const s = d.toString().trim();
    if (s) {
      this.logLines.push(s);
      if (this.logLines.length > 200) this.logLines.shift();
    }
  }

  // 轮询等待后端 HTTP 就绪
  _waitReady(role) {
    const port = this.port();
    return new Promise((resolve) => {
      const deadline = Date.now() + 20000;
      const check = () => {
        const http = require("http");
        const req = http.get({ host: "127.0.0.1", port, path: "/api/health", timeout: 2000 }, (res) => {
          res.resume();
          resolve(true);
        });
        req.on("error", () => {
          if (Date.now() > deadline) {
            resolve(false);
          } else {
            setTimeout(check, 500);
          }
        });
      };
      check();
    });
  }

  stop() {
    if (this.proc && !this.proc.killed) {
      this.proc.kill();
      this.proc = null;
    }
    this.role = null;
  }
}

module.exports = { BackendManager, loadEnv };
