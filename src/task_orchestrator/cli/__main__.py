"""A2A 服务端入口:把 Main Agent 图包成 A2A 1.0 服务,供组长 PT 下发任务。

运行:``python -m task_orchestrator.cli`` (默认 role=member,监听 a2a_port=8101)

组员 PT 收到组长下发的子任务文本 → LangGraphAgentExecutor 跑 Main Agent 图
→ 组员自己再规划(设置提醒/文件操作/开发任务) → 返回 final_response 作为 A2A artifact。
"""

from __future__ import annotations

import argparse
import logging

from a2a.types import AgentCapabilities, AgentInterface, AgentSkill

from task_orchestrator.adapters.a2a_executor import LangGraphAgentExecutor
from task_orchestrator.adapters.a2a_server import build_a2a_app, build_agent_card, run_agent
from task_orchestrator.api.server import build_registry
from task_orchestrator.common.config import get_settings
from task_orchestrator.common.llm import build_chat_model
from task_orchestrator.common.log import setup_logging
from task_orchestrator.main_agent.graph import build_main_agent

logger = logging.getLogger("cli")


def main() -> None:
    parser = argparse.ArgumentParser(description="Task Orchestrator A2A 服务端")
    parser.add_argument("--role", choices=["leader", "member"], default=None,
                        help="角色(默认取 PTA_A2A_ROLE,再默认 member)")
    parser.add_argument("--port", type=int, default=None, help="监听端口(默认取 PTA_A2A_PORT)")
    args = parser.parse_args()

    settings = get_settings()
    role = args.role or settings.a2a_role
    port = args.port or settings.a2a_port
    setup_logging("task_orchestrator", settings.log_level, settings.log_format)

    model = build_chat_model()
    registry = build_registry(model, role=role)
    graph = build_main_agent(model, registry, role=role)

    url = f"http://{settings.bind_host}:{port}"
    card = build_agent_card(
        name=settings.a2a_agent_name,
        description=settings.a2a_agent_description,
        url=url,
        skills=[
            AgentSkill(
                id="execute_subtask",
                name="执行组长下发的子任务",
                description="接收组长分派的子任务文本,在本地规划并执行,返回执行结果。",
                tags=["subtask", "execute"],
                examples=["请在明天下午3点设置提醒开会"],
            ),
        ],
        streaming=True,
    )

    executor = LangGraphAgentExecutor(graph, agent_name=settings.a2a_agent_name)
    app = build_a2a_app(card, executor, api_key=settings.a2a_api_key)

    # 向注册中心登记本实例(组员),并尝试向组长发加入申请
    if settings.registry_url:
        _register_and_join(settings, url)

    logger.info("A2A 服务端启动", extra={"role": role, "port": port, "url": url})
    run_agent(app, settings.bind_host, port)


def _register_and_join(settings, url: str) -> None:
    """启动时注册到注册中心;组员且配置了 leader_id 则发起加入申请。"""
    import asyncio

    from task_orchestrator.registry_client import RegistryClient, register_instance

    async def _do() -> None:
        peer_id = await register_instance(settings, url)
        if peer_id is not None and settings.leader_id:
            client = RegistryClient(settings.registry_url)
            try:
                rid = await client.join_request(
                    peer_id, settings.instance_name, url, int(settings.leader_id)
                )
                logger.info("已向组长发起加入申请", extra={"request_id": rid})
            except Exception as exc:
                logger.warning("发起加入申请失败", extra={"error": str(exc)})
            finally:
                await client.close()

    try:
        asyncio.run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.warning("注册中心登记/申请失败(继续启动)", extra={"error": str(exc)})


if __name__ == "__main__":
    main()
