"""LLM 工厂:OpenAI 兼容 ChatModel 构造 + 角色分档模型路由 + 测试用确定性假模型。"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from task_orchestrator.common.config import TIER_NAMES, Settings, get_settings


def ai_text(text: str) -> AIMessage:
    return AIMessage(content=text)


def ai_tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class ScriptedChatModel(BaseChatModel):
    """确定性假模型:responses(FIFO) + rules(关键词) + default_response。

    tier 字段用于标记该实例属于哪个角色档位(测试断言路由用)。
    """

    responses: list[AIMessage] = []
    rules: list[tuple[str, AIMessage]] = []
    default_response: str = "好的,已收到。"
    tier: str = ""

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _pick(self, messages: list[BaseMessage]) -> AIMessage:
        if self.responses:
            msg = self.responses.pop(0)
        else:
            last_text = str(messages[-1].content) if messages else ""
            msg = next(
                (reply for keyword, reply in self.rules if keyword in last_text),
                AIMessage(content=self.default_response),
            )
        copied = msg.model_copy(deep=True)
        copied.id = None
        return copied

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: Any = None, **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._pick(messages))])


class StructuredScriptedModel(ScriptedChatModel):
    """输出 JSON 结构的假模型(用于 plan_node)。"""

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: Any = None, **kwargs: Any,
    ) -> ChatResult:
        msg = self._pick(messages)
        parsed = msg.content
        if hasattr(msg, "additional_kwargs"):
            parsed = msg.additional_kwargs.get("structured_output", parsed)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=str(parsed)))])


def build_chat_model(settings: Settings | None = None, tier: str | None = None) -> BaseChatModel:
    """构造 ChatModel。

    tier 指定且 PTA_MODEL_TIERS 中配置了该档位时,用档位配置覆盖
    model/base_url/api_key/temperature;否则回退 PTA_LLM_*(单模型模式)。"""
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        tag = f"[{tier}]" if tier else ""
        return ScriptedChatModel(
            default_response=f"(fake-llm{tag}) 我已收到你的请求。",
            tier=tier or "",
        )

    cfg = settings.get_model_tier(tier) if tier else None
    model_name = cfg.model if cfg else settings.llm_model
    base_url = cfg.base_url if cfg and cfg.base_url else settings.llm_base_url
    api_key = cfg.api_key if cfg and cfg.api_key else settings.llm_api_key
    temperature = (
        cfg.temperature if cfg and cfg.temperature is not None else settings.llm_temperature
    )
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )


def build_tier_models(
    settings: Settings | None = None, tier_names: tuple[str, ...] = TIER_NAMES,
) -> dict[str, BaseChatModel]:
    """为所有角色档位构造模型字典 {tier: model}。

    未在 PTA_MODEL_TIERS 里配置的档位,回退到默认模型(所有未配置档位共享同一实例)。
    fake provider 下每个档位各自独立实例(带 tier 标签,便于测试断言路由)。
    """
    settings = settings or get_settings()
    result: dict[str, BaseChatModel] = {}
    for name in tier_names:
        if settings.llm_provider == "fake":
            result[name] = ScriptedChatModel(
                default_response=f"(fake-{name}) 已收到。",
                tier=name,
            )
        else:
            result[name] = build_chat_model(settings, tier=name)
    return result
