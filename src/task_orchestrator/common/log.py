"""结构化日志:JSON/Console 双格式,contextvars 贯穿 request_id/context_id。"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_context_id_var: ContextVar[str] = ContextVar("context_id", default="")


def bind_context(request_id: str = "", context_id: str = "") -> None:
    if request_id:
        _request_id_var.set(request_id)
    if context_id:
        _context_id_var.set(context_id)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = _request_id_var.get()
        cid = _context_id_var.get()
        if rid:
            payload["request_id"] = rid
        if cid:
            payload["context_id"] = cid
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in getattr(record, "extra", {}).items():
            payload[key] = val
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        rid = _request_id_var.get()
        cid = _context_id_var.get()
        ctx = ""
        if rid:
            ctx += f"[{rid[:8]}]"
        if cid:
            ctx += f"[{cid[:8]}]"
        return f"{ts} {record.levelname:5s} {record.name:20s} {ctx} {record.getMessage()}"


def setup_logging(
    name: str = "task_orchestrator", level: str = "INFO", fmt: str = "console",
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter() if fmt == "json" else ConsoleFormatter())
        logger.addHandler(handler)
    return logger
