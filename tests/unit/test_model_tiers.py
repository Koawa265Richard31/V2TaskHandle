"""角色分档模型配置与路由:PTA_MODEL_TIERS 解析、按档位构造模型、fake 档位标签。"""
from __future__ import annotations

import pytest

from task_orchestrator.common.config import Settings
from task_orchestrator.common.llm import (
    ScriptedChatModel,
    build_chat_model,
    build_tier_models,
)

_JSON = (
    '[{"tier":"planner","model":"deepseek-ai/DeepSeek-R1"},'
    '{"tier":"implementer","model":"Pro/deepseek-ai/DeepSeek-V3.2","temperature":0.3}]'
)


def _settings(**kw) -> Settings:
    base = dict(
        llm_provider="openai",
        llm_model="fallback-model",
        llm_base_url="https://fallback.example.com",
        llm_api_key="sk-fallback",
        model_tiers_json=_JSON,
    )
    base.update(kw)
    return Settings(**base)


def test_parse_model_tiers():
    s = _settings()
    tiers = s.model_tiers
    assert set(tiers) == {"planner", "implementer"}
    assert tiers["planner"].model == "deepseek-ai/DeepSeek-R1"
    assert tiers["implementer"].model == "Pro/deepseek-ai/DeepSeek-V3.2"
    assert tiers["implementer"].temperature == 0.3
    # 未配置档位返回 None
    assert s.get_model_tier("reviewer") is None


def test_parse_invalid_tiers_ignored():
    s = _settings(model_tiers_json='[{"tier":"planner"},{"tier":"","model":"x"},{"tier":"evaluator","model":"ok"}]')
    tiers = s.model_tiers
    assert set(tiers) == {"evaluator"}


def _base_url(model) -> str:
    # langchain-openai 新旧版本属性名兼容
    return getattr(model, "openai_api_base", None) or getattr(model, "base_url", "")


def test_build_chat_model_tier_override():
    s = _settings()
    model = build_chat_model(s, tier="implementer")
    assert model.model_name == "Pro/deepseek-ai/DeepSeek-V3.2"
    assert model.temperature == 0.3
    assert _base_url(model) == "https://fallback.example.com"  # 继承 base_url


def test_build_chat_model_fallback_when_tier_unset():
    s = _settings()
    model = build_chat_model(s, tier="reviewer")  # 未配置 → 回退
    assert model.model_name == "fallback-model"
    assert build_chat_model(s).model_name == "fallback-model"


def test_build_chat_model_tier_base_url_override():
    s = _settings(model_tiers_json=(
        '[{"tier":"reviewer","model":"m2","base_url":"https://other.example.com","temperature":0.5}]'
    ))
    model = build_chat_model(s, tier="reviewer")
    assert model.model_name == "m2"
    assert _base_url(model) == "https://other.example.com"
    assert model.temperature == 0.5


def test_fake_tier_tag():
    s = Settings(llm_provider="fake")
    model = build_tier_models(s)
    assert set(model) == {"planner", "architect", "implementer", "reviewer", "evaluator"}
    # fake 下每个档位是独立实例且带标签
    assert model["planner"].tier == "planner"
    assert model["implementer"].tier == "implementer"
    assert model["planner"] is not model["implementer"]
    # 默认 build_chat_model(fake) 不带档位标签
    plain = build_chat_model(s)
    assert plain.tier == ""


def test_fake_tier_default_response_tagged():
    s = Settings(llm_provider="fake")
    models = build_tier_models(s)
    async def _invoke(m):
        return await m.ainvoke([("human", "hi")])
    import asyncio
    resp = asyncio.run(_invoke(models["implementer"]))
    assert "(fake-implementer)" in str(resp.content)


def test_scripted_tier_attr():
    m = ScriptedChatModel(default_response="x", tier="planner")
    assert m.tier == "planner"


def test_invalid_json_returns_empty():
    s = _settings(model_tiers_json="not-json")
    assert s.model_tiers == {}