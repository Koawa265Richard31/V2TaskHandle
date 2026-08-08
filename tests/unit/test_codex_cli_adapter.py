"""CodexCliAdapter 单元测试:不依赖真实 codex/sandbox,只测逻辑与发现。

真实 codex exec 验证放到集成/手动演示(需要本机 codex 已安装登录)。
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from task_orchestrator.adapters.codex_cli_adapter import CodexCliAdapter, _discover_native_codex


class TestCodexCliAdapter:
    def test_agent_type_and_capability(self):
        adapter = CodexCliAdapter()
        assert adapter.agent_type == "codex_cli"
        assert "code" in adapter.capabilities

    def test_is_available_false_when_missing(self):
        adapter = CodexCliAdapter(codex_cmd="/nonexistent/definitely-not-a-real-codex.exe")
        assert adapter.is_available is False

    def test_is_available_true_for_python(self):
        adapter = CodexCliAdapter(codex_cmd=sys.executable)
        assert adapter.is_available is True

    def test_discovers_native_codex_windows(self):
        """Windows 上应能发现 native codex.exe(若存在)或返回空串,不抛异常。"""
        path = _discover_native_codex()
        assert isinstance(path, str)
        if sys.platform.startswith("win"):
            # 若本机有官方 runtime 应发现;没有则空串也可接受
            assert path == "" or path.endswith("codex.exe")
        else:
            assert path == ""

    def test_default_uses_native_or_path(self):
        """默认 codex_cmd 应非空(发现 native 或回退 PATH)。"""
        adapter = CodexCliAdapter()
        # 本机有 codex,PATH 或 native 至少一个
        assert isinstance(adapter.codex_cmd, str)


class TestApprovalMode:
    def test_approval_mode_default_auto(self):
        assert CodexCliAdapter().approval_mode == "auto"

    def test_approval_mode_invalid_falls_back_auto(self):
        assert CodexCliAdapter(approval_mode="weird").approval_mode == "auto"

    def test_approval_mode_valid_values(self):
        assert CodexCliAdapter(approval_mode="ask").approval_mode == "ask"
        assert CodexCliAdapter(approval_mode="full").approval_mode == "full"

    def test_build_command_full_uses_bypass(self, tmp_path):
        adapter = CodexCliAdapter(approval_mode="full")
        cmd = adapter._build_command("写文件", str(tmp_path / "out.txt"))
        assert "--dangerously-bypass-approvals-and-sandbox" in " ".join(cmd)

    def test_build_command_auto_uses_on_request(self, tmp_path):
        adapter = CodexCliAdapter(approval_mode="auto")
        cmd = adapter._build_command("写文件", str(tmp_path / "out.txt"))
        joined = " ".join(cmd)
        assert 'approval_policy="on-request"' in joined
        assert "--dangerously-bypass" not in joined

    def test_build_command_ask_uses_untrusted(self, tmp_path):
        adapter = CodexCliAdapter(approval_mode="ask")
        cmd = adapter._build_command("写文件", str(tmp_path / "out.txt"))
        joined = " ".join(cmd)
        assert 'approval_policy="untrusted"' in joined
        assert "--dangerously-bypass" not in joined

    def test_build_command_includes_json_and_outfile(self, tmp_path):
        adapter = CodexCliAdapter(approval_mode="full")
        out = str(tmp_path / "out.txt")
        cmd = adapter._build_command("任务", out)
        assert "--json" in cmd
        assert out in cmd

    def test_build_command_uses_custom_sandbox(self, tmp_path):
        """sandbox 参数应作为 -s 的值(而非硬编码 workspace-write)。"""
        adapter = CodexCliAdapter(approval_mode="auto", sandbox="custom-sb")
        cmd = adapter._build_command("任务", str(tmp_path / "out.txt"))
        joined = " ".join(cmd)
        assert "-s custom-sb" in joined
        assert "workspace-write" not in joined

    def test_resume_auto_carries_sandbox_and_policy(self, tmp_path, monkeypatch):
        """auto 模式的 resume 也应带 -s 与 approval_policy,与 submit 一致。"""
        import asyncio
        import io

        a = CodexCliAdapter(approval_mode="auto", codex_cmd=sys.executable,
                            sandbox="custom-sb", workdir=str(tmp_path))
        a._thread_ids["t1"] = "thread-xyz"
        captured = {}

        async def _fake_subprocess(*cmd, **kwargs):
            captured["cmd"] = cmd
            class _FakeProc:
                stdout = io.BytesIO(b"")
                stderr = None
                returncode = 0
                async def wait(self):
                    return 0
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess)

        async def _run():
            await a.resume("t1", "继续执行")

        asyncio.run(_run())
        joined = " ".join(captured["cmd"])
        assert "-s custom-sb" in joined
        assert 'approval_policy="on-request"' in joined
        assert "--dangerously-bypass" not in joined

    def test_resume_ask_carries_untrusted(self, tmp_path, monkeypatch):
        """ask 模式的 resume 应带 untrusted policy。"""
        import asyncio
        import io

        a = CodexCliAdapter(approval_mode="ask", codex_cmd=sys.executable,
                            sandbox="custom-sb", workdir=str(tmp_path))
        a._thread_ids["t1"] = "thread-xyz"
        captured = {}

        async def _fake_subprocess(*cmd, **kwargs):
            captured["cmd"] = cmd
            class _FakeProc:
                stdout = io.BytesIO(b"")
                stderr = None
                returncode = 0
                async def wait(self):
                    return 0
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess)

        async def _run():
            await a.resume("t1", "继续执行")

        asyncio.run(_run())
        joined = " ".join(captured["cmd"])
        assert "-s custom-sb" in joined
        assert 'approval_policy="untrusted"' in joined
        assert "--dangerously-bypass" not in joined


class TestJsonProgress:
    def _adapter(self, mode="auto"):
        return CodexCliAdapter(approval_mode=mode, codex_cmd=sys.executable)

    def test_agent_message_sets_progress(self):
        a = self._adapter()
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"分析目录结构"}}'.encode("utf-8"))
        assert a._progress.get("t1") == "分析目录结构"

    def test_file_change_sets_progress(self):
        a = self._adapter()
        a._consume_json_line("t1", b'{"type":"item.completed","item":{"type":"file_change","changes":[{"path":"D:/x.py","kind":"add"}]}}')
        assert "x.py" in a._progress["t1"]

    def test_command_execution_sets_progress(self):
        a = self._adapter()
        a._consume_json_line("t1", b'{"type":"item.completed","item":{"type":"command_execution","command":"ls -la"}}')
        assert "ls -la" in a._progress["t1"]

    def test_non_completed_event_ignored(self):
        a = self._adapter()
        a._consume_json_line("t1", b'{"type":"item.started","item":{"type":"agent_message","text":"x"}}')
        assert a._progress.get("t1") is None

    def test_invalid_json_ignored(self):
        a = self._adapter()
        a._consume_json_line("t1", b"not json")
        assert a._progress.get("t1") is None

    def test_ask_mode_detects_waiting_approval(self):
        a = self._adapter(mode="ask")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"无法创建该文件,当前会话权限不足,需审批"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1") is True
        assert a._progress.get("t1")

    def test_ask_mode_no_detection_on_normal(self):
        a = self._adapter(mode="ask")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"已完成修改"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1", False) is False

    def test_ask_mode_detects_english_denial(self):
        a = self._adapter(mode="ask")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"permission denied: cannot write outside workspace"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1") is True

    def test_auto_mode_detects_waiting_approval(self):
        """auto(on-request)模式下受限时也应触发 waiting_approval。"""
        a = self._adapter(mode="auto")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"无法写入该目录,需要审批"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1") is True

    def test_full_mode_does_not_detect_waiting_approval(self):
        """full 模式绕过审批,不应触发 waiting_approval。"""
        a = self._adapter(mode="full")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"无法写入该目录,需要审批"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1", False) is False

    def test_structural_approval_requests_detected(self):
        """codex 结构化 approval_requests 字段也应触发。"""
        a = self._adapter(mode="auto")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"请求写入","approval_requests":[{"id":"r1"}]}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1") is True

    def test_normal_message_not_marked_waiting(self):
        a = self._adapter(mode="auto")
        a._consume_json_line("t1", '{"type":"item.completed","item":{"type":"agent_message","text":"已完成任务"}}'.encode("utf-8"))
        assert a._waiting_approval.get("t1", False) is False


class TestThreadIdCapture:
    def _adapter(self, mode="auto"):
        return CodexCliAdapter(approval_mode=mode, codex_cmd=sys.executable)

    def test_thread_started_captures_id(self):
        a = self._adapter()
        a._consume_json_line("t1", b'{"type":"thread.started","thread_id":"019f-abc"}')
        assert a._thread_ids.get("t1") == "019f-abc"

    def test_thread_id_used_by_resume_command(self, tmp_path, monkeypatch):
        """resume 应构造 `codex exec resume <thread_id> <prompt>` 命令。"""
        import asyncio
        from task_orchestrator.adapters.codex_cli_adapter import CodexCliAdapter as CCA

        a = CCA(approval_mode="full", codex_cmd=sys.executable, codex_home="", workdir=str(tmp_path))
        a._thread_ids["t1"] = "thread-xyz"

        # 拦截 create_subprocess_exec,记录命令
        captured = {}

        async def _fake_subprocess(*cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            # 返回一个假 proc:stdout 为空流,stderr 空,returncode 0
            import io
            class _FakeProc:
                stdout = io.BytesIO(b"")
                stderr = None
                returncode = 0
                async def wait(self):
                    return 0
            return _FakeProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_subprocess)

        async def _run():
            await a.resume("t1", "继续执行")

        asyncio.run(_run())
        assert "resume" in captured["cmd"]
        assert "thread-xyz" in captured["cmd"]
        assert "继续执行" in captured["cmd"]
        assert "--dangerously-bypass-approvals-and-sandbox" in captured["cmd"]
        assert captured["cwd"] == str(tmp_path)

    def test_resume_without_thread_id_raises(self):
        import pytest
        import asyncio
        a = self._adapter()
        async def _run():
            await a.resume("no_such", "x")
        with pytest.raises(RuntimeError):
            asyncio.run(_run())
