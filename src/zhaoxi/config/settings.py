"""Central application settings."""

from pydantic import Field
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

    def validate_model_config(self) -> None:
        """Raise a readable error when required live-model settings are absent."""
        missing = []
        if not self.model_api_key:
            missing.append("ZHAOXI_MODEL_API_KEY")
        if not self.model_name:
            missing.append("ZHAOXI_MODEL_NAME")
        if missing:
            raise ConfigError(f"缺少模型配置：{', '.join(missing)}。请复制 .env.example 为 .env 后填写。")
