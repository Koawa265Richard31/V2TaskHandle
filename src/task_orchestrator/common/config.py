"""全局配置:pydantic-settings 统一管理,环境变量前缀 ``PTA_``,支持 .env 文件。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class A2AAgentConfig(BaseSettings):
    """单个 A2A 远端 Agent 配置。"""
    name: str = ""
    url: str = ""
    api_key: str = ""


class ExternalAgentConfig(BaseSettings):
    """单个远端 REST 垂类 Agent(如检索)配置。"""
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    capability: str = "retrieve"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PTA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ── LLM(OpenAI 兼容) ────────────────────────────────────────
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: SecretStr = SecretStr("")
    llm_temperature: float = 0.0

    # ── A2A 远端 Agent ──────────────────────────────────────────
    a2a_agents_json: str = Field(
        default="[]",
        validation_alias=AliasChoices("PTA_A2A_AGENTS", "PTA_A2A_AGENTS_JSON"),
    )
    # 远端 REST 垂类 Agent(如检索),JSON 数组: [{name, base_url, api_key, capability}]
    external_agents_json: str = Field(
        default="[]",
        validation_alias=AliasChoices("PTA_EXTERNAL_AGENTS", "PTA_EXTERNAL_AGENTS_JSON"),
    )
    a2a_api_key: str = ""
    # 向组员下发时的请求超时(秒):组员用真实 LLM 执行可能较慢
    a2a_timeout: float = 300.0
    # 角色:leader(组长,可向组员下发任务 + 读组员报告) / member(组员,只能被下发 + 发报告)
    a2a_role: Literal["leader", "member"] = "member"
    # 组员作为 A2A 服务端监听的端口(组长通过它下发)
    a2a_port: int = 8101
    a2a_agent_name: str = "Team Member PT"
    a2a_agent_description: str = (
        "团队组员个人任务 Agent:接收组长下发的子任务并在本地规划执行"
        "(设置提醒/文件操作/开发任务),完成任务后通过邮件向组长提交任务报告书。"
        "本 Agent 不接受对其他 Agent 的下发请求。"
    )

    # ── Codex ───────────────────────────────────────────────────
    codex_enabled: bool = False
    codex_sandbox: str = "workspace_write"
    codex_model: str = "gpt-5.4"
    # 本机 codex CLI 适配器(包装 codex exec,注册现成 coding agent)
    codex_cli_enabled: bool = False
    codex_cli_cmd: str = ""
    codex_cli_workdir: str = "./data/codex-workspace"
    # codex 主目录(配置/认证/sandbox 组件)。留空用默认 ~/.codex。
    # Windows 多 codex 安装(桌面版/CLI)时必须显式指定,否则用错账号或找不到组件。
    codex_cli_home: str = ""
    # codex 审批模式: ask(强提醒人工介入) / auto(自动执行) / full(完全绕过)。
    # 映射 codex approval_policy: ask→untrusted, auto→on-request, full→bypass
    codex_approval_mode: Literal["ask", "auto", "full"] = "auto"

    # ── 本地 Agent ──────────────────────────────────────────────
    local_tools: str = "shell,file,web"

    # ── 网络 ────────────────────────────────────────────────────
    bind_host: str = "127.0.0.1"
    api_port: int = 8000

    # ── 注册中心(云端 PT 协作) ───────────────────────────────────
    # 中央注册中心地址:PT 实例启动时向它登记,跨环境发现彼此
    registry_url: str = ""
    # 注册中心服务监听端口(registry_center 模块用)
    registry_port: int = 9000
    # 本 PT 实例的标识与展示信息
    instance_name: str = "My PT"
    instance_description: str = ""
    # 组长 id(组员用它发加入团队申请;leader 不需要)
    leader_id: str = ""

    # ── 邮箱(可选) ──────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    email_from: str = ""
    imap_host: str = ""
    imap_port: int = 993

    # ── 数据与日志 ──────────────────────────────────────────────
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    def db_path(self, name: str) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / f"{name}.db"

    @property
    def a2a_agents(self) -> list[A2AAgentConfig]:
        import json
        try:
            raw = json.loads(self.a2a_agents_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return [
            A2AAgentConfig(
                name=item.get("name", ""),
                url=item.get("url", ""),
                api_key=item.get("api_key", self.a2a_api_key),
            )
            for item in raw
        ]

    @property
    def external_agents(self) -> list[ExternalAgentConfig]:
        import json
        try:
            raw = json.loads(self.external_agents_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return [
            ExternalAgentConfig(
                name=item.get("name", ""),
                base_url=item.get("base_url", item.get("url", "")),
                api_key=item.get("api_key", ""),
                capability=item.get("capability", "retrieve"),
            )
            for item in raw
        ]

    @property
    def local_tool_list(self) -> list[str]:
        return [t.strip() for t in self.local_tools.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
