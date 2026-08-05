"""Agent 适配器基类与统一接口。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from task_orchestrator.main_agent.state import SubTask


class BaseAdapter(ABC):
    """所有 SubAgent 适配器的统一接口。"""

    @abstractmethod
    async def submit(self, task: dict) -> str:
        """提交任务,返回外部 task_id（用于后续查询/取消）。"""

    @abstractmethod
    async def status(self, external_id: str) -> str:
        """查询任务状态: pending/running/completed/failed。"""

    @abstractmethod
    async def result(self, external_id: str) -> str | None:
        """获取任务结果（终态后调用）。"""

    @abstractmethod
    async def cancel(self, external_id: str) -> bool:
        """取消任务,返回是否成功。"""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """适配器类型标识: a2a | codex | local | retrieval。"""

    @property
    def name(self) -> str:
        """实例名(注册名)。子类可覆盖,默认空。"""
        return ""

    @property
    def capabilities(self) -> list[str]:
        """能力列表(如 ["retrieve"]、["code"]、["doc"])。默认空,可覆盖。"""
        return []

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """该适配器当前是否可用。"""
