"""最小 ReAct 工具循环:所有 LLM 型 Agent 共用的图构建器。"""
from __future__ import annotations

from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


def build_tool_agent(
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str | Callable[[], str],
    checkpointer=None,
):
    bound = model.bind_tools(tools) if tools else model

    def call_model(state: MessagesState) -> dict:
        prompt = system_prompt() if callable(system_prompt) else system_prompt
        response = bound.invoke([SystemMessage(content=prompt), *state["messages"]])
        return {"messages": [response]}

    def route(state: MessagesState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    if tools:
        graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "model")
    if tools:
        graph.add_conditional_edges("model", route, {"tools": "tools", END: END})
        graph.add_edge("tools", "model")
    else:
        graph.add_edge("model", END)
    return graph.compile(checkpointer=checkpointer)
