"""本地工具 Agent:Shell/文件/网页操作 + ReAct 循环。"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool, tool

from task_orchestrator.common.agent_loop import build_tool_agent

# ── 工具定义 ──────────────────────────────────────────────


@tool
def shell_exec(command: str) -> str:
    """执行 Shell 命令并返回 stdout+stderr。禁止 rm -rf /、format 等危险操作。
    适用场景:列出文件、查看 git log、运行测试、查找文本等。"""
    blocked = ["rm -rf /", "format c:", "del /f /s", "shutdown", "reboot"]
    cmd_lower = command.lower().strip()
    for b in blocked:
        if b in cmd_lower:
            return f"危险命令已拦截: {b}"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
            cwd=str(Path.cwd()),
        )
        out = result.stdout.strip() or "(无输出)"
        if result.stderr.strip():
            out += f"\n[stderr]\n{result.stderr.strip()}"
        return out[:3000]
    except subprocess.TimeoutExpired:
        return "命令超时 (30s)"
    except Exception as exc:
        return f"命令执行失败: {exc}"


@tool
def file_read(path: str) -> str:
    """读取文本文件内容。"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"文件不存在: {path}"
    if p.stat().st_size > 1024 * 500:
        return f"文件过大 ({p.stat().st_size} bytes),请用 grep 或其他方式搜索。"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as exc:
        return f"读取失败: {exc}"


@tool
def file_write(content: str, path: str) -> str:
    """将内容写入文件（覆盖模式）。"""
    p = Path(path).expanduser().resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字符到 {p}"
    except Exception as exc:
        return f"写入失败: {exc}"


@tool
async def web_fetch(url: str) -> str:
    """通过 HTTP GET 获取网页内容（返回文本摘要,最多 5000 字符）。"""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, follow_redirects=True)
            text = resp.text[:5000]
            return text
    except Exception as exc:
        return f"请求失败: {exc}"


# ── 邮件工具(SMTP 发送 / IMAP 读取,需 .env 配置 smtp_*/imap_*) ─────


def _mail_settings():
    from task_orchestrator.common.config import get_settings
    return get_settings()


def _check_mail_config(need: list[str]) -> str | None:
    """校验邮件配置,缺失则返回错误文案。"""
    s = _mail_settings()
    missing = [k for k in need if not getattr(s, k)]
    if missing:
        return f"未配置邮箱参数: {', '.join(missing)}。请在 .env 中设置后再用邮件功能。"
    return None


@tool
async def email_send(to: str, subject: str, body: str) -> str:
    """通过 SMTP 发送邮件。参数: to(收件人邮箱), subject(主题), body(正文)。
    用于向组长汇报任务报告书等场景。"""
    import asyncio
    from email.mime.text import MIMEText
    import smtplib

    err = _check_mail_config(["smtp_host", "smtp_user", "smtp_password", "email_from"])
    if err:
        return err
    s = _mail_settings()
    password = s.smtp_password.get_secret_value()

    def _send() -> str:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = s.email_from
        msg["To"] = to
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
                server.starttls()
                server.login(s.smtp_user, password)
                server.sendmail(s.email_from, [to], msg.as_string())
            return f"邮件已发送至 {to}"
        except Exception as exc:
            return f"邮件发送失败: {exc}"

    return await asyncio.to_thread(_send)


@tool
async def email_read(folder: str = "INBOX", limit: int = 10) -> str:
    """通过 IMAP 读取邮箱最近邮件。folder 默认 INBOX,limit 为读取条数。
    用于组长读取组员发来的任务报告书等场景。"""
    import asyncio
    import imaplib
    import email as eml
    from email.header import decode_header

    err = _check_mail_config(["imap_host", "smtp_user", "smtp_password"])
    if err:
        return err
    s = _mail_settings()
    password = s.smtp_password.get_secret_value()

    def _read() -> str:
        def _dec(s: str) -> str:
            if not s:
                return ""
            try:
                parts = decode_header(s)
                return "".join(
                    p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
                    for p, enc in parts
                )
            except Exception:
                return str(s)

        try:
            conn = imaplib.IMAP4_SSL(s.imap_host, s.imap_port, timeout=15)
            conn.login(s.smtp_user, password)
            conn.select(folder, readonly=True)
            _, data = conn.search(None, "ALL")
            ids = data[0].split()
            if not ids:
                conn.logout()
                return "邮箱为空"
            lines = []
            for mid in ids[-limit:]:
                _, msg_data = conn.fetch(mid, "(RFC822)")
                msg = eml.message_from_bytes(msg_data[0][1])
                subj = _dec(msg.get("Subject", ""))
                from_ = _dec(msg.get("From", ""))
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body_text = part.get_payload(decode=True).decode(
                                "utf-8", errors="replace"
                            )[:500]
                            break
                else:
                    body_text = msg.get_payload(decode=True).decode(
                        "utf-8", errors="replace"
                    )[:500]
                lines.append(f"[{from_}] {subj}\n{body_text}")
            conn.logout()
            return "\n---\n".join(lines)
        except Exception as exc:
            return f"邮件读取失败: {exc}"

    return await asyncio.to_thread(_read)


def _system_prompt() -> str:
    now = datetime.now().isoformat(timespec="seconds")
    return f"""你是本地工具执行 Agent,可以执行 Shell 命令、读写文件、获取网页内容。
当前时间:{now}

规则:
1. 用户委托你执行具体操作,完成后用一两句话汇报结果
2. 如果需要调用 shell,确保命令安全无害
3. 文件操作前确认路径正确
4. 遇到错误如实向用户说明"""


def build_local_agent(
    model: BaseChatModel,
    enabled_tools: list[str] | None = None,
    checkpointer=None,
):
    """构建本地工具 Agent 的 ReAct 图。"""
    available = {
        "shell": shell_exec,
        "file_read": file_read,
        "file_write": file_write,
        "web": web_fetch,
        "email_send": email_send,
        "email_read": email_read,
    }
    if enabled_tools is None:
        enabled_tools = list(available.keys())
    tools: list[BaseTool] = [
        t for name, t in available.items() if name in enabled_tools or "file" in name and ("file_read" if name == "file_read" else True)
    ]
    # 简化:按工具名精确匹配,同时处理 "file" 展开为 file_read + file_write
    resolved: list[BaseTool] = []
    for t in enabled_tools:
        if t == "file":
            for n in ["file_read", "file_write"]:
                tool_obj = available.get(n)
                if tool_obj and tool_obj not in resolved:
                    resolved.append(tool_obj)
        elif t in available:
            resolved.append(available[t])
        elif f"{t}" in available:
            resolved.append(available[f"{t}"])
        elif f"file_{t}" in available:
            resolved.append(available[f"file_{t}"])
    tools = [t for t in resolved if t is not None]
    return build_tool_agent(model, tools, _system_prompt, checkpointer=checkpointer)
