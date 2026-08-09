"""Agent 适配器:统一接口(A2A / Codex / Local / Retrieval / MCP 等)。"""

from task_orchestrator.adapters.a2a_adapter import A2AAdapter
from task_orchestrator.adapters.base import BaseAdapter
from task_orchestrator.adapters.codex_adapter import CodexAdapter
from task_orchestrator.adapters.codex_cli_adapter import CodexCliAdapter
from task_orchestrator.adapters.local_adapter import LocalAdapter
from task_orchestrator.adapters.mcp_adapter import McpAgentAdapter
from task_orchestrator.adapters.retrieval_adapter import RetrievalAdapter
