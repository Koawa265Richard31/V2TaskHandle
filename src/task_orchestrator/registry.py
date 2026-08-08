"""Agent 注册中心:管理所有 SubAgent 适配器实例。"""
from __future__ import annotations

import logging

from task_orchestrator.adapters.a2a_adapter import A2AAdapter
from task_orchestrator.adapters.base import BaseAdapter
from task_orchestrator.adapters.codex_adapter import CodexAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter

logger = logging.getLogger("registry")


class AgentRegistry:
    """管理所有可用的 SubAgent 适配器。"""

    def __init__(self):
        self._adapters: dict[str, BaseAdapter] = {}
        self._by_type: dict[str, list[str]] = {}

    def register(self, adapter: BaseAdapter, name: str = "") -> str:
        """注册一个适配器,返回注册名。"""
        name = name or f"{adapter.agent_type}_{len(self._adapters)}"
        self._adapters[name] = adapter
        self._by_type.setdefault(adapter.agent_type, []).append(name)
        logger.info("注册 Agent 适配器", extra={"name": name, "type": adapter.agent_type})
        return name

    def get(self, name: str) -> BaseAdapter | None:
        return self._adapters.get(name)

    def get_by_type(self, agent_type: str) -> BaseAdapter | None:
        """返回该类型第一个可用的适配器。"""
        names = self._by_type.get(agent_type, [])
        for name in names:
            adapter = self._adapters[name]
            if adapter.is_available:
                return adapter
        return None

    def get_by_capability(self, capability: str) -> BaseAdapter | None:
        """返回具备指定能力(如 "retrieve"/"code"/"doc")的第一个可用适配器。"""
        for adapter in self._adapters.values():
            if capability in adapter.capabilities and adapter.is_available:
                return adapter
        return None

    def list_all(self) -> list[dict]:
        """列出所有已注册的 Agent(含可用状态)。"""
        result = []
        for name, adapter in self._adapters.items():
            result.append({
                "name": name,
                "type": adapter.agent_type,
                "available": adapter.is_available,
                "status": "online" if adapter.is_available else "offline",
            })
        return result

    def agents_summary(self) -> str:
        """生成 Agent 摘要文本,用于注入 plan 提示词。"""
        lines = []
        for name, adapter in self._adapters.items():
            status = "可用" if adapter.is_available else "不可用"
            caps = f" 能力:{','.join(adapter.capabilities)}" if adapter.capabilities else ""
            lines.append(f"- {name} (type={adapter.agent_type}, {status}{caps})")
        return "\n".join(lines)

    @classmethod
    async def from_config(cls, settings) -> "AgentRegistry":
        """从 Settings 构造 AgentRegistry (M5 中连接 dispatch/monitor 用)。"""
        registry = cls()

        # A2A agents
        for agent_cfg in settings.a2a_agents:
            adapter = A2AAdapter(agent_cfg.url, agent_cfg.api_key)
            await adapter.connect()
            registry.register(adapter, agent_cfg.name or f"a2a_{len(registry._adapters)}")

        # Codex
        codex_sandbox = getattr(settings, "codex_sandbox", "workspace_write")
        codex_model = getattr(settings, "codex_model", "gpt-5.4")
        codex = CodexAdapter(sandbox=codex_sandbox, model=codex_model)
        registry.register(codex, "codex")

        # Local
        local = LocalAdapter(enabled_tools=settings.local_tool_list)
        registry.register(local, "local")

        return registry
