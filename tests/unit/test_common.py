"""common 层单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from task_orchestrator.common.config import Settings
from task_orchestrator.common.db import Database
from task_orchestrator.common.llm import (
    ScriptedChatModel,
    ai_text,
    ai_tool_call,
    build_chat_model,
)
from langchain_core.messages import HumanMessage


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    monkeypatch.setenv("PTA_LLM_PROVIDER", "fake")
    monkeypatch.delenv("PTA_LLM_API_KEY", raising=False)


class TestConfig:
    def test_defaults(self):
        s = Settings(_env_file=None, llm_provider="openai")
        assert s.api_port == 8000

    def test_local_tool_list(self):
        s = Settings(_env_file=None, local_tools="shell, email , file")
        assert s.local_tool_list == ["shell", "email", "file"]

    def test_a2a_agents_parsing(self):
        s = Settings(
            _env_file=None,
            a2a_agents_json='[{"name":"test","url":"http://x.com"}]',
        )
        agents = s.a2a_agents
        assert len(agents) == 1
        assert agents[0].name == "test"

    def test_external_agents_parsing(self):
        s = Settings(
            _env_file=None,
            external_agents_json=(
                '[{"name":"retrieval-web","base_url":"https://r.example.com","api_key":"k","capability":"retrieve"}]'
            ),
        )
        agents = s.external_agents
        assert len(agents) == 1
        assert agents[0].name == "retrieval-web"
        assert agents[0].capability == "retrieve"
        assert agents[0].base_url == "https://r.example.com"

    def test_external_agents_default_capability(self):
        s = Settings(
            _env_file=None,
            external_agents_json='[{"name":"x","base_url":"http://x.com"}]',
        )
        assert s.external_agents[0].capability == "retrieve"

    def test_external_agents_invalid_json(self):
        s = Settings(_env_file=None, external_agents_json="not-json")
        assert s.external_agents == []

    def test_db_path_creates_dir(self, tmp_path):
        s = Settings(_env_file=None, data_dir=tmp_path / "sub")
        p = s.db_path("test")
        assert p.parent.exists()


class TestDatabase:
    def test_insert_and_query(self, tmp_path):
        db = Database(tmp_path / "t.db")
        db.execute("CREATE TABLE x (id INTEGER PRIMARY KEY, val TEXT)")
        rid = db.insert("INSERT INTO x(val) VALUES (?)", ("hi",))
        assert rid == 1
        rows = db.query("SELECT * FROM x")
        assert len(rows) == 1
        assert rows[0]["val"] == "hi"
        db.close()

    def test_migrate_idempotent(self, tmp_path):
        db = Database(tmp_path / "t.db")
        db.migrate("m1", ["CREATE TABLE m (id INTEGER)"])
        db.migrate("m1", ["CREATE TABLE m (id INTEGER)"])
        db.close()

    def test_wal_mode(self, tmp_path):
        db = Database(tmp_path / "t.db")
        row = db.query("PRAGMA journal_mode")[0]
        assert "wal" in str(row).lower()
        db.close()


class TestFakeLLM:
    def test_fifo(self):
        model = ScriptedChatModel(responses=[ai_text("A"), ai_text("B")])
        assert model.invoke([HumanMessage("x")]).content == "A"
        assert model.invoke([HumanMessage("x")]).content == "B"
        assert model.invoke([HumanMessage("x")]).content == "好的,已收到。"

    def test_rules(self):
        model = ScriptedChatModel(
            rules=[("报销", ai_tool_call("create_task", {"title": "报销单"}))],
        )
        out = model.invoke([HumanMessage("明天交报销单")])
        assert out.tool_calls[0]["name"] == "create_task"

    def test_factory_fake(self):
        s = Settings(_env_file=None, llm_provider="fake")
        m = build_chat_model(s)
        assert isinstance(m, ScriptedChatModel)
