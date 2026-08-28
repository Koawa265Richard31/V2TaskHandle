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
    """单个远端 REST 垂类 Agent(如检索/MCP)配置。"""
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    capability: str = "retrieve"
    agent_type: str = "retrieval"  # retrieval | mcp


# 流水线角色(模型分档的档位名)。用户可用这些名字在 PTA_MODEL_TIERS 里配置各自模型。
TIER_NAMES: tuple[str, ...] = (
    "planner",      # 强:意图理解 / 任务规划 / 规划落地文档 / 重规划
    "architect",    # 强:开发落地文档(模块/切片/验收标准)
    "implementer",  # 便宜:按切片实现(高频、量大)
    "reviewer",     # 强/中:逐切片审查(PASS/FAIL,限次退回)
    "evaluator",    # 强:整体评估报告(只对照验收列差距,不下"能否上线"结论)
)


class ModelTierConfig(BaseSettings):
    """单个角色档位的模型配置。base_url/api_key/temperature 留空则继承 PTA_LLM_*。"""
    tier: str = ""
    model: str = ""
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    temperature: float | None = None


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

    # 角色分档模型(模型路由):JSON 数组 [{tier, model, base_url?, api_key?, temperature?}]
    # tier ∈ planner/architect/implementer/reviewer/evaluator;缺省项回退到 PTA_LLM_* 单模型
    model_tiers_json: str = Field(
        default="[]",
        validation_alias=AliasChoices("PTA_MODEL_TIERS", "PTA_MODEL_TIERS_JSON"),
    )

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
    # 组长定时刷新已批准组员缓存的间隔(秒);<=0 表示关闭定时刷新
    peer_refresh_seconds: float = 15.0

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
                agent_type=item.get("agent_type", "retrieval"),
            )
            for item in raw
        ]

    @property
    def model_tiers(self) -> dict[str, ModelTierConfig]:
        """解析 PTA_MODEL_TIERS 为 {tier: ModelTierConfig}。非法项跳过。"""
        import json

        try:
            raw = json.loads(self.model_tiers_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        tiers: dict[str, ModelTierConfig] = {}
        for item in raw:
            tier = str(item.get("tier", "")).strip()
            model = str(item.get("model", "")).strip()
            if not tier or not model:
                continue
            tiers[tier] = ModelTierConfig(
                tier=tier,
                model=model,
                base_url=str(item.get("base_url", "")).strip(),
                api_key=SecretStr(str(item.get("api_key", "") or "")),
                temperature=item.get("temperature"),
            )
        return tiers

    def get_model_tier(self, tier: str) -> ModelTierConfig | None:
        """取某个角色的档位配置;未配置返回 None(调用方回退 PTA_LLM_*)。"""
        return self.model_tiers.get(tier)

    @property
    def local_tool_list(self) -> list[str]:
        return [t.strip() for t in self.local_tools.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
