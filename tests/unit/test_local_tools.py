"""本地工具测试。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from task_orchestrator.common.llm import ScriptedChatModel, ai_text
from task_orchestrator.local_agent.tools import (
    build_local_agent,
    email_read,
    email_send,
    file_read,
    file_write,
    shell_exec,
    web_fetch,
)


class TestEmailTools:
    def _patch_settings(self, monkeypatch, **overrides):
        from task_orchestrator.common import config as cfg
        from pydantic import SecretStr

        defaults = dict(
            smtp_host="", smtp_port=587, smtp_user="", smtp_password=SecretStr(""),
            email_from="", imap_host="", imap_port=993,
        )
        defaults.update(overrides)
        monkeypatch.setattr(cfg, "get_settings", lambda: cfg.Settings(_env_file=None, **defaults))

    @pytest.mark.asyncio
    async def test_email_send_missing_config(self, monkeypatch):
        """未配置 SMTP 时应返回清晰错误而非崩溃。"""
        self._patch_settings(monkeypatch)
        r = await email_send.ainvoke({"to": "a@b.com", "subject": "s", "body": "b"})
        assert "未配置" in r

    @pytest.mark.asyncio
    async def test_email_send_with_mock_smtp(self, monkeypatch):
        """配置齐全时走真实 SMTP 调用(用 mock 替换)。"""
        import smtplib
        from pydantic import SecretStr

        class _FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, u, p): pass
            def sendmail(self, f, t, m): pass

        monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
        self._patch_settings(monkeypatch,
            smtp_host="smtp.example.com", smtp_port=587,
            smtp_user="u", smtp_password=SecretStr("p"), email_from="from@example.com")
        r = await email_send.ainvoke({"to": "boss@example.com", "subject": "报告书", "body": "本周完成情况"})
        assert "已发送" in r

    @pytest.mark.asyncio
    async def test_email_read_missing_config(self, monkeypatch):
        self._patch_settings(monkeypatch)
        r = await email_read.ainvoke({})
        assert "未配置" in r


class TestShellExec:
    def test_blocks_dangerous(self):
        result = shell_exec.invoke("rm -rf /home")
        assert "拦截" in result

    def test_simple_command(self):
        result = shell_exec.invoke("echo hello")
        assert "hello" in result


class TestFileTools:
    def test_write_and_read(self, tmp_path):
        p = tmp_path / "test.txt"
        r = file_write.invoke({"content": "hello world", "path": str(p)})
        assert "已写入" in r
        content = file_read.invoke(str(p))
        assert "hello world" in content

    def test_read_missing(self):
        r = file_read.invoke("/nonexistent/path.txt")
        assert "不存在" in r


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_invalid_url(self):
        r = await web_fetch.ainvoke({"url": "not-a-valid-url"})
        assert "失败" in r


class TestBuildAgent:
    def test_builds_with_tools(self):
        model = ScriptedChatModel()
        graph = build_local_agent(model, enabled_tools=["shell", "file_read"])
        assert graph is not None

    def test_builds_all_tools(self):
        model = ScriptedChatModel()
        graph = build_local_agent(model)
        assert graph is not None

    @pytest.mark.asyncio
    async def test_repl_loop_execute(self):
        model = ScriptedChatModel(
            responses=[ai_text("命令已执行,输出: hello")]
        )
        graph = build_local_agent(model, enabled_tools=[])
        result = await graph.ainvoke({"messages": [{"role": "user", "content": "执行 echo hello"}]})
        assert result is not None
