"""Codex CLI 适配器:包装本机 codex exec 非交互执行。

与 CodexAdapter(openai-codex Python SDK)不同,这里直接调本机安装的 codex CLI,
实现"注册现成 coding agent"——不需要 Python SDK,只要有 codex 可执行文件即可。

调用形式:
    codex exec --skip-git-repo-check -s <sandbox> -m <model> -o <out_file> "<prompt>"
-o 会把 agent 的最后一条消息写到 out_file,作为任务结果。

Windows 兼容:
- 不走 sh/shim——PATH 里的 codex 可能是 .cmd/.bat shim 或 POSIX 脚本,
  经 sh 调用会触发 sandbox-setup 加载失败("找不到指定的模块")。
- 优先用 native codex.exe:配置 codex_cmd 时用它,否则自动从常见位置发现
  (~/.codex 的 bin、AppData\\Local\\OpenAI\\Codex\\bin\\<hash>\\codex.exe)。
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import platform
import shutil
import sys
import uuid
from pathlib import Path

from task_orchestrator.adapters.base import BaseAdapter

logger = logging.getLogger("adapters.codex_cli")


def _discover_native_codex() -> str:
    """自动发现本机 native codex.exe(Windows)。返回路径或空串。

    优先级:
    1. 显式配置(通过 codex_cmd 传入,不含这里)
    2. PATH 中 codex 所在目录旁的 codex-cli-data/.sandbox-bin/codex.exe
       (如 D:\\software\\codex-cli\\codex-cli-data\\.sandbox-bin\\codex.exe)
    3. 官方 runtime(AppData\\Local\\OpenAI\\Codex\\bin\\<hash>\\codex.exe)
    """
    if platform.system() != "Windows":
        return ""
    candidates: list[str] = []

    # 2) PATH 中 codex 所在目录旁的 .sandbox-bin
    path_codex = shutil.which("codex")
    if path_codex:
        base_dir = os.path.dirname(os.path.abspath(path_codex))
        candidates.append(os.path.join(base_dir, "codex-cli-data", ".sandbox-bin", "codex.exe"))

    # 3) 官方 runtime
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OpenAI" / "Codex" / "bin"
    for d in sorted(glob.glob(str(base / "*" / "codex.exe"))):
        candidates.append(d)
    for d in sorted(glob.glob(str(base / "codex.exe"))):
        candidates.append(d)

    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""


class CodexCliAdapter(BaseAdapter):
    """包装本机 codex CLI。submit 在后台跑 codex exec,status/result 轮询结果。

    approval_mode 三层审批:
    - full → --dangerously-bypass-approvals-and-sandbox(完全绕过,现状默认)
    - auto → -c approval_policy="on-request"(自动执行,按需请求)
    - ask  → -c approval_policy="untrusted"(受限操作时 codex 返回需人工介入说明)
    注:exec 非交互模式下 codex 无法真正人工介入,受限操作被拒绝并说明。
    sandbox 说明:D盘 CLI 的 sandbox 组件不完整,workspace-write/elevated 写文件会失败,
    用 danger-full-access(绕过 sandbox)才能真实写文件。可在构造时用 sandbox 参数覆盖。
    """

    def __init__(
        self,
        workdir: str | None = None,
        model: str | None = None,
        sandbox: str = "danger-full-access",
        approval_mode: str = "auto",
        codex_cmd: str = "",
        codex_home: str = "",
        timeout: float = 300.0,
    ):
        self.workdir = workdir or "./data/codex-workspace"
        self.model = model
        self.sandbox = sandbox
        self.approval_mode = approval_mode if approval_mode in ("ask", "auto", "full") else "auto"
        # codex_cmd 为空时:优先 native exe,否则回退 PATH 中的 codex
        self.codex_cmd = codex_cmd or _discover_native_codex() or shutil.which("codex") or ""
        # CODEX_HOME:codex 的主目录(配置/认证/sandbox 组件)。为空时用默认 ~/.codex
        self.codex_home = codex_home
        self.timeout = timeout
        self._tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._progress: dict[str, str] = {}
        self._waiting_approval: dict[str, bool] = {}
        # 每个任务的 codex thread_id(来自 thread.started 事件,用于 resume 恢复会话)
        self._thread_ids: dict[str, str] = {}

    @property
    def agent_type(self) -> str:
        return "codex_cli"

    @property
    def capabilities(self) -> list[str]:
        return ["code"]

    @property
    def is_available(self) -> bool:
        return bool(self.codex_cmd) and os.path.isfile(self.codex_cmd)

    def _build_command(self, description: str, out_file: str) -> list[str]:
        """构造 codex exec 命令。三层审批 → codex 参数。"""
        cmd = [
            self.codex_cmd, "exec",
            "--skip-git-repo-check",
            "--json",
            "-o", out_file,
            # 指定工作根目录:codex 的操作(读写文件)落在 workdir,而非进程 cwd。
            # 不设子进程 cwd(codex 的 Windows sandbox 组件被切换工作目录时按相对
            # 路径找依赖会弹"找不到文件"),用 -C 让 codex 内部切根目录。
            "-C", self.workdir,
        ]
        if self.approval_mode == "full":
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.approval_mode == "ask":
            cmd += ["-s", "workspace-write", "-c", 'approval_policy="untrusted"']
        else:  # auto
            cmd += ["-s", "workspace-write", "-c", 'approval_policy="on-request"']
        if self.model:
            cmd += ["-m", self.model]
        cmd.append(description)
        return cmd

    async def submit(self, task: dict) -> str:
        """后台启动 codex exec(--json 流式),返回内部 task_id。"""
        if not self.is_available:
            raise RuntimeError(f"codex CLI「{self.codex_cmd}」不可用(文件不存在)")
        os.makedirs(self.workdir, exist_ok=True)
        task_id = f"codex_{uuid.uuid4().hex[:8]}"
        description = task.get("description", "")
        out_file = os.path.join(self.workdir, f".codex_out_{task_id}.txt")
        cmd = self._build_command(description, out_file)

        # 继承当前环境,并注入 CODEX_HOME(如配置)
        env = dict(os.environ)
        if self.codex_home:
            env["CODEX_HOME"] = self.codex_home

        async def _run() -> None:
            try:
                # 注意:不设 cwd。codex 的 Windows sandbox 组件在子进程被切换工作目录
                # 时按相对路径找依赖,会弹"找不到文件"。继承当前进程 cwd 可避免。
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # 逐行读 stdout 解析 --json 事件,提取进度
                assert proc.stdout is not None
                async for line in proc.stdout:
                    self._consume_json_line(task_id, line)
                stderr = await proc.stderr.read() if proc.stderr else b""
                await proc.wait()
                # 读 -o 输出文件(终态结果)
                if os.path.exists(out_file):
                    with open(out_file, encoding="utf-8") as f:
                        self._results[task_id] = f.read().strip()
                if proc.returncode != 0 and task_id not in self._results:
                    self._errors[task_id] = stderr.decode("utf-8", errors="replace").strip()
            except asyncio.TimeoutError:
                self._errors[task_id] = f"codex exec 超时({self.timeout}s)"
                logger.warning("codex 执行超时", extra={"task_id": task_id})
            except Exception as exc:
                self._errors[task_id] = str(exc)
                logger.error("codex 执行失败", extra={"task_id": task_id, "error": str(exc)})

        run = asyncio.create_task(_run())
        self._tasks[task_id] = run
        logger.info("codex 任务已提交", extra={"task_id": task_id, "approval_mode": self.approval_mode})
        return task_id

    def _consume_json_line(self, task_id: str, line: bytes) -> None:
        """解析 codex --json 事件行,更新进度/审批状态。"""
        import json as _json
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            ev = _json.loads(text)
        except _json.JSONDecodeError:
            return
        # thread.started → 记录 thread_id(用于 resume 恢复会话)
        if ev.get("type") == "thread.started":
            tid = ev.get("thread_id")
            if tid:
                self._thread_ids[task_id] = tid
            return
        if ev.get("type") != "item.completed":
            return
        item = ev.get("item") or {}
        itype = item.get("type")
        # agent_message 文本 → 进度
        if itype == "agent_message" and item.get("text"):
            self._progress[task_id] = item["text"][:300]
        # file_change → 记录"修改文件 X"
        elif itype == "file_change":
            changes = item.get("changes") or []
            paths = [c.get("path", "") for c in changes if c.get("path")]
            if paths:
                self._progress[task_id] = f"修改文件: {', '.join(paths)}"
        # command_execution → 记录执行命令
        elif itype == "command_execution" and item.get("command"):
            self._progress[task_id] = f"执行命令: {item['command'][:200]}"
        # ask 模式检测:agent_message 含受限拒绝说明 → waiting_approval
        if itype == "agent_message" and self.approval_mode == "ask":
            msg = item.get("text") or ""
            if any(k in msg for k in ("无法", "不能写入", "审批", "权限", "只读", "拒绝")):
                self._waiting_approval[task_id] = True

    async def progress(self, external_id: str) -> str | None:
        """获取任务最新进度文本。"""
        return self._progress.get(external_id)

    async def is_waiting_approval(self, external_id: str) -> bool:
        """ask 模式下是否等待人工介入。"""
        return self._waiting_approval.get(external_id, False)

    async def status(self, external_id: str) -> str:
        run = self._tasks.get(external_id)
        if run is None:
            return "failed"
        if run.done():
            return "completed" if external_id not in self._errors else "failed"
        return "running"

    async def result(self, external_id: str) -> str | None:
        if external_id in self._errors:
            return None
        return self._results.get(external_id)

    async def resume(self, external_id: str, prompt: str) -> None:
        """恢复某任务对应的 codex 会话,继续执行 prompt。

        用 `codex exec resume <thread_id> <prompt>`(非交互)。cd 到 workdir
        使 codex 操作落在工作根目录。上下文保留(codex 记得之前做了什么)。
        供审批闭环(auto 批准继续 / 改策略重跑)复用原会话,避免丢失上下文。
        """
        thread_id = self._thread_ids.get(external_id)
        if not thread_id:
            raise RuntimeError(f"任务 {external_id} 无 codex thread_id,无法 resume(可能未捕获 thread.started)")
        cmd = [
            self.codex_cmd, "exec", "resume",
            thread_id, prompt,
        ]
        if self.approval_mode == "full":
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        env = dict(os.environ)
        if self.codex_home:
            env["CODEX_HOME"] = self.codex_home
        logger.info("resume codex 会话", extra={"task_id": external_id, "thread_id": thread_id})

        async def _run() -> None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=self.workdir, env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                assert proc.stdout is not None
                async for line in proc.stdout:
                    self._consume_json_line(external_id, line)
                stderr = await proc.stderr.read() if proc.stderr else b""
                await proc.wait()
                if proc.returncode != 0 and external_id not in self._results:
                    self._errors[external_id] = stderr.decode("utf-8", errors="replace").strip()
            except Exception as exc:
                self._errors[external_id] = str(exc)

        run = asyncio.create_task(_run())
        self._tasks[external_id] = run

    async def cancel(self, external_id: str) -> bool:
        run = self._tasks.get(external_id)
        if run and not run.done():
            run.cancel()
            return True
        return False

    async def close(self) -> None:
        for run in list(self._tasks.values()):
            if not run.done():
                run.cancel()
