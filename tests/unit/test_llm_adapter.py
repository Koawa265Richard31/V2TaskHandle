"""LlmAdapter(implementer):便宜档位模型执行切片。"""
from __future__ import annotations

import asyncio

from task_orchestrator.adapters.llm_adapter import LlmAdapter
from task_orchestrator.common.llm import ScriptedChatModel, ai_text


def _run(coro):
    return asyncio.run(coro)


def _model(default: str = "切片交付物内容", tier: str = "implementer") -> ScriptedChatModel:
    return ScriptedChatModel(default_response=default, tier=tier)


def test_agent_type_and_capabilities():
    adapter = LlmAdapter(model=_model())
    assert adapter.agent_type == "implementer"
    assert adapter.name == "implementer"
    assert "write" in adapter.capabilities
    assert adapter.is_available


def test_not_available_without_model():
    assert not LlmAdapter(model=None).is_available


def test_submit_status_result_roundtrip():
    adapter = LlmAdapter(model=_model(default="DONE-TEXT"))
    task = {"task_id": "1", "description": "写一段产品介绍", "agent_type": "implementer"}
    ext = _run(adapter.submit(task))
    assert ext.startswith("impl-")
    assert _run(adapter.status(ext)) == "completed"
    assert _run(adapter.result(ext)) == "DONE-TEXT"
    assert _run(adapter.cancel(ext)) is True
    assert _run(adapter.status(ext)) == "running"


def test_carries_dependency_context_to_model():
    """submit 时把任务内依赖上下文拼进 HumanMessage(供便宜模型理解上游产物)。"""
    captured: list[str] = []

    class CapturingModel(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            captured.append(str(messages[-1].content))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    adapter = LlmAdapter(model=CapturingModel(default_response="OK"))
    task = {
        "task_id": "2",
        "description": "基于检索结果写摘要",
        "context": "[1] 检索资料\n内容ABC",
        "agent_type": "implementer",
    }
    _run(adapter.submit(task))
    assert len(captured) == 1
    assert "内容ABC" in captured[0]
    assert "检索资料" in captured[0]


def test_prompt_warns_no_answer_prefix():
    """提示词要求直接产出,不加"以下是…"前缀(通过脚本模型默认输出已满足)。"""
    adapter = LlmAdapter(model=_model())
    ext = _run(adapter.submit({"task_id": "1", "description": "x", "agent_type": "implementer"}))
    assert _run(adapter.result(ext)) == "切片交付物内容"