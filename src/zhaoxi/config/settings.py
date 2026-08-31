"""Central application settings."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zhaoxi.errors import ConfigError


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ZHAOXI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = ""
    log_level: str = "INFO"
    max_agent_steps: int = Field(default=8, ge=1, le=100)
    request_timeout_seconds: float = Field(default=60, gt=0)
    max_context_messages: int = Field(default=40, ge=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    memory_db_path: str = ".zhaoxi/memory.db"
    memory_retrieval_limit: int = Field(default=6, ge=1, le=50)
    memory_context_max_chars: int = Field(default=4000, ge=200, le=50_000)
    planner_enabled: bool = True
    planner_max_steps: int = Field(default=12, ge=1, le=100)
    planner_max_replans: int = Field(default=3, ge=0, le=20)
    planner_max_attempts_per_step: int = Field(default=2, ge=1, le=10)
    planner_step_timeout_seconds: float = Field(default=30, gt=0)
    planner_total_timeout_seconds: float = Field(default=180, gt=0)
    planner_trace_max_events: int = Field(default=200, ge=10, le=10_000)
    cognitive_router_enabled: bool = True
    auto_memory_enabled: bool = True
    memory_importance_keep_threshold: float = Field(default=0.75, ge=0, le=1)
    memory_relevance_active_threshold: float = Field(default=0.60, ge=0, le=1)
    memory_importance_forget_threshold: float = Field(default=0.30, ge=0, le=1)
    memory_relevance_forget_threshold: float = Field(default=0.20, ge=0, le=1)
    memory_relevance_decay_per_day: float = Field(default=0.01, ge=0, le=1)
    memory_relevance_access_boost: float = Field(default=0.15, ge=0, le=1)
    memory_cold_archive_after_days: float = Field(default=30, ge=0)
    permission_read_policy: str = "allow"
    permission_write_policy: str = "confirm"
    permission_delete_policy: str = "confirm"
    permission_external_action_policy: str = "confirm"
    permission_dangerous_policy: str = "deny"
    permission_confirmation_ttl_seconds: float = Field(default=300, gt=0)
    permission_audit_path: str = ".zhaoxi/audit/permission.jsonl"
    permission_max_tool_output_chars: int = Field(default=12_000, ge=200, le=100_000)
    workflow_enabled: bool = True
    workflow_directory: str = "workflows"
    workflow_db_path: str = ".zhaoxi/workflow.db"
    workflow_history_limit: int = Field(default=100, ge=1, le=1000)
    workflow_max_steps: int = Field(default=50, ge=1, le=500)
    workflow_max_events: int = Field(default=200, ge=10, le=10_000)
    lifehud_base_url: str = "http://127.0.0.1:8025"
    lifehud_context_path: str = "/api/agent/context"
    lifehud_schema_version: str = "1"
    lifehud_timeout_seconds: float = Field(default=10, gt=0, le=120)
    lifehud_max_retries: int = Field(default=2, ge=0, le=5)
    lifehud_display_timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_planner_limits(self) -> "Settings":
        valid_permission_policies = {"allow", "confirm", "deny"}
        configured_policies = {
            self.permission_read_policy,
            self.permission_write_policy,
            self.permission_delete_policy,
            self.permission_external_action_policy,
            self.permission_dangerous_policy,
        }
        if not configured_policies <= valid_permission_policies:
            raise ValueError("permission policy 必须是 allow、confirm 或 deny")
        if self.planner_step_timeout_seconds > self.planner_total_timeout_seconds:
            raise ValueError("planner step timeout 不能大于 total timeout")
        if self.planner_max_attempts_per_step > self.planner_max_steps:
            raise ValueError("planner 每步尝试次数不能大于总执行步数")
        if self.memory_importance_forget_threshold >= self.memory_importance_keep_threshold:
            raise ValueError("memory importance 遗忘阈值必须低于保留阈值")
        if self.memory_relevance_forget_threshold >= self.memory_relevance_active_threshold:
            raise ValueError("memory relevance 遗忘阈值必须低于活跃阈值")
        return self

    def validate_model_config(self) -> None:
        """Raise a readable error when required live-model settings are absent."""
        missing = []
        if not self.model_api_key:
            missing.append("ZHAOXI_MODEL_API_KEY")
        if not self.model_name:
            missing.append("ZHAOXI_MODEL_NAME")
        if missing:
            raise ConfigError(f"缺少模型配置：{', '.join(missing)}。请复制 .env.example 为 .env 后填写。")
