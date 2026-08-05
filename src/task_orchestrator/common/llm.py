"""LLM 工厂:OpenAI 兼容 ChatModel 构造 + 测试用确定性假模型。"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from task_orchestrator.common.config import Settings, get_settings


def ai_text(text: str) -> AIMessage:
    return AIMessage(content=text)


def ai_tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class ScriptedChatModel(BaseChatModel):
    """确定性假模型:responses(FIFO) + rules(关键词) + default_response。"""

    responses: list[AIMessage] = []
    rules: list[tuple[str, AIMessage]] = []
    default_response: str = "好的,已收到。"

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


def build_chat_model(settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        return ScriptedChatModel(default_response="(fake-llm) 我已收到你的请求。")
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
    )
