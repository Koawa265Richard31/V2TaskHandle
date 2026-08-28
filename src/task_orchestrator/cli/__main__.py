"""Task Orchestrator 命令行入口。

子命令:
  serve   A2A 服务端入口:把 Main Agent 图包成 A2A 1.0 服务,供组长 PT 下发任务。
          运行: python -m task_orchestrator.cli serve [--role member|leader] [--port 8101]
          不传子命令时默认等同 serve(保持向后兼容)。
  chat    项目原型流水线(自用命令行):给一句粗构想 → 规划/开发文档 →
          切片执行(便宜模型档)→ 逐片审查 → 整体评估,产物落盘 data/projects/。
          运行: python -m task_orchestrator.cli chat "我想做一个……" [--role leader]
          不带消息参数进入交互模式。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from a2a.types import AgentCapabilities, AgentInterface, AgentSkill

from task_orchestrator.adapters.a2a_executor import LangGraphAgentExecutor
from task_orchestrator.adapters.a2a_server import build_a2a_app, build_agent_card, run_agent
from task_orchestrator.api.server import build_registry
from task_orchestrator.cli.run import interactive_repl, run_chat
from task_orchestrator.common.config import get_settings
from task_orchestrator.common.llm import build_chat_model, build_tier_models
from task_orchestrator.common.log import setup_logging
from task_orchestrator.main_agent.graph import build_main_agent

logger = logging.getLogger("cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="task_orchestrator.cli")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="A2A 服务端(默认子命令)")
    serve_p.add_argument("--role", choices=["leader", "member"], default=None,
                         help="角色(默认取 PTA_A2A_ROLE,再默认 member)")
    serve_p.add_argument("--port", type=int, default=None, help="监听端口(默认取 PTA_A2A_PORT)")

    chat_p = sub.add_parser("chat", help="项目原型流水线(命令行自用)")
    chat_p.add_argument("message", nargs="?", default=None,
                        help="一次性任务构想;省略则进入交互模式")
    chat_p.add_argument("--role", choices=["leader", "member"], default="leader",
                        help="本实例角色(默认 leader,可向组员下发;自用一般 leader)")
    chat_p.add_argument("--project-dir", default=None,
                        help="产物落盘目录(默认 data/projects/<项目ID>)")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    settings = get_settings()
    setup_logging("task_orchestrator", settings.log_level, settings.log_format)

    cmd = args.command or "serve"
    if cmd == "chat":
        _chat(args, settings)
    else:
        _serve(args, settings)


def _chat(args, settings) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if args.message:
            loop.run_until_complete(
                run_chat(settings, args.message, role=args.role, project=args.project_dir)
            )
        else:
            loop.run_until_complete(
                interactive_repl(settings, role=args.role, project=args.project_dir)
            )
    finally:
        loop.close()


def _serve(args, settings) -> None:
    role = args.role or settings.a2a_role
    port = args.port or settings.a2a_port

    model = build_chat_model(settings)
    tier_models = build_tier_models(settings)
    registry = build_registry(model, role=role, tier_models=tier_models)
    graph = build_main_agent(model, registry, role=role, models=tier_models)

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