"""注册中心服务入口:``python -m task_orchestrator.registry_center``。

监听 ``PTA_REGISTRY_PORT``(默认 9000),数据存 ``{data_dir}/registry.db``。
"""

from __future__ import annotations

import logging

from task_orchestrator.common.config import get_settings
from task_orchestrator.registry_center.app import build_app, build_db

logger = logging.getLogger("registry_center")


def main() -> None:
    import uvicorn

    settings = get_settings()
    db = build_db(settings.db_path("registry"))
    app = build_app(db)
    port = settings.registry_port
    logger.info("注册中心启动", extra={"port": port})
    uvicorn.run(app, host=settings.bind_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
