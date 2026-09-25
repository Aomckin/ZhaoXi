"""Central application settings."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zhaoxi.errors import ConfigError


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_prefix="ZHAOXI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    desktop_activity_enabled: bool = True
    desktop_activity_window_title_enabled: bool = True
    desktop_activity_input_rate_enabled: bool = True
    desktop_activity_title_buffer_minutes: int = Field(default=20, ge=10, le=30)
    desktop_activity_sample_interval_seconds: float = Field(default=2, ge=1, le=5)
    desktop_activity_inference_interval_seconds: float = Field(default=60, ge=30, le=120)
    desktop_activity_keyboard_busy_grace_seconds: float = Field(default=15, ge=1, le=60)
    desktop_activity_high_keyboard_rate: float = Field(default=120, gt=0)
    desktop_activity_high_mouse_rate: float = Field(default=180, gt=0)
    desktop_activity_deep_work_seconds: float = Field(default=1200, ge=60)

    active_beat_min_silence_seconds: int = Field(default=180, ge=1, le=3600)
    active_beat_cooldown_seconds: int = Field(default=300, ge=1, le=3600)
    active_beat_initial_budget: int = Field(default=2, ge=0, le=3)
    active_beat_max_budget: int = Field(default=3, ge=1, le=3)

    model_base_url: str = "https://api.openai.com/v1"
    model_api_key: str = ""
    model_name: str = ""
    model_fallback_base_url: str = ""
    model_fallback_api_key: str = ""
    model_fallback_name: str = ""
    log_level: str = "INFO"
    log_path: str = ".zhaoxi/logs/zhaoxi.log"
    log_max_bytes: int = Field(default=10_485_760, ge=1024, le=1_000_000_000)
    log_backup_count: int = Field(default=5, ge=1, le=100)
    shutdown_grace_seconds: float = Field(default=15, gt=0, le=300)
    max_agent_steps: int = Field(default=8, ge=1, le=100)
    tool_overrides_path: str = "data/debug/tool_overrides.json"
    filesystem_access_path: str = ".zhaoxi/filesystem-access.json"
    tool_router_mode: str = Field(default="dynamic", pattern="^(dynamic|all)$")
    emoji_enabled: bool = True
    emoji_registry_path: str = "data/emoji/emoji_registry.json"
    emoji_recent_history_size: int = Field(default=5, ge=1, le=50)
    emoji_candidate_limit: int = Field(default=5, ge=1, le=20)
    emoji_min_match_score: float = Field(default=0.4, ge=0, le=1)
    request_timeout_seconds: float = Field(default=60, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    retry_max_delay_seconds: float = Field(default=8, ge=0, le=300)
    provider_failure_threshold: int = Field(default=5, ge=1, le=100)
    provider_cooldown_seconds: float = Field(default=60, ge=0, le=3600)
    request_max_model_calls: int = Field(default=12, ge=1, le=100)
    request_max_total_tokens: int = Field(default=100_000, ge=1_000, le=10_000_000)
    request_extension_1_limit_tokens: int = Field(default=25_000, ge=0, le=10_000_000)
    request_extension_2_limit_tokens: int = Field(default=15_000, ge=0, le=10_000_000)
    request_hard_limit_tokens: int | None = Field(default=None, ge=1_000, le=10_000_000)
    request_finalization_reserve_tokens: int = Field(default=8_000, ge=0, le=1_000_000)
    request_budget_warning_ratio: float = Field(default=0.85, gt=0, lt=1)
    max_context_messages: int = Field(default=40, ge=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    memory_db_path: str = ".zhaoxi/memory.db"
    memory_retrieval_limit: int = Field(default=6, ge=1, le=50)
    memory_context_max_chars: int = Field(default=4000, ge=200, le=50_000)
    memory_per_cluster_limit: int = Field(default=2, ge=1, le=20)
    memory_graph_max_hops: int = Field(default=2, ge=0, le=2)
    memory_graph_min_edge_weight: float = Field(default=0.25, ge=0, le=1)
    memory_auto_consolidation_enabled: bool = True
    memory_consolidate_after_episodes: int = Field(default=25, ge=2, le=1000)
    memory_consolidation_interval_hours: float = Field(default=24, gt=0, le=720)
    memory_consolidation_min_evidence: int = Field(default=3, ge=2, le=100)
    memory_cluster_embedding_enabled: bool = True
    memory_cluster_match_threshold: float = Field(default=0.38, ge=0, le=1)
    memory_cluster_merge_threshold: float = Field(default=0.84, ge=0, le=1)
    memory_edge_extraction_enabled: bool = True
    agenda_context_enabled: bool = True
    agenda_db_path: str = ".zhaoxi/agenda.db"
    agenda_max_context_items: int = Field(default=8, ge=1, le=30)
    short_term_memory_db_path: str = ".zhaoxi/short-term-memory.db"
    current_cognition_db_path: str = ".zhaoxi/current-cognition.db"
    working_notes_db_path: str = ".zhaoxi/working-notes.db"  # Legacy backup only; never read as context.
    archive_enabled: bool = True
    archive_directory: str = "data/archive"
    archive_db_path: str = ".zhaoxi/archive.db"
    archive_search_top_k: int = Field(default=5, ge=1, le=20)
    archive_context_max_chars: int = Field(default=6000, ge=200, le=50_000)
    archive_max_document_chars: int = Field(default=12_000, ge=200, le=100_000)
    archive_chunk_max_chars: int = Field(default=3000, ge=500, le=20_000)
    archive_chunk_overlap_chars: int = Field(default=200, ge=0, le=2000)
    planner_enabled: bool = True
    planner_db_path: str = ".zhaoxi/planner.db"
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
    memory_activation_active_threshold: float = Field(default=0.60, ge=0, le=1)
    memory_activation_dormant_threshold: float = Field(default=0.20, ge=0, le=1)
    memory_activation_decay_per_day: float = Field(default=0.01, ge=0, le=1)
    memory_activation_access_boost: float = Field(default=0.12, ge=0, le=1)
    memory_cold_dormant_after_days: float = Field(default=30, ge=0)
    memory_dormant_archive_after_days: float = Field(default=90, ge=0)
    permission_read_policy: str = "allow"
    permission_write_policy: str = "confirm"
    permission_delete_policy: str = "confirm"
    permission_external_action_policy: str = "confirm"
    permission_dangerous_policy: str = "deny"
    permission_confirmation_ttl_seconds: float = Field(default=300, gt=0)
    permission_audit_path: str = ".zhaoxi/audit/permission.jsonl"
    permission_audit_max_bytes: int = Field(default=10_485_760, ge=1024, le=1_000_000_000)
    permission_audit_backup_count: int = Field(default=5, ge=1, le=100)
    permission_db_path: str = ".zhaoxi/permission.db"
    permission_max_tool_output_chars: int = Field(default=12_000, ge=200, le=100_000)
    workflow_enabled: bool = True
    workflow_directory: str = "workflows"
    workflow_db_path: str = ".zhaoxi/workflow.db"
    workflow_history_limit: int = Field(default=100, ge=1, le=1000)
    workflow_max_steps: int = Field(default=50, ge=1, le=500)
    workflow_max_events: int = Field(default=200, ge=10, le=10_000)
    reflection_enabled: bool = True
    reflection_db_path: str = ".zhaoxi/reflection.db"
    reflection_timezone: str = "Asia/Shanghai"
    reflection_max_evidence: int = Field(default=200, ge=1, le=5000)
    reflection_max_evidence_chars: int = Field(default=40_000, ge=1000, le=1_000_000)
    reflection_max_excerpt_chars: int = Field(default=800, ge=50, le=2000)
    reflection_prompt_version: int = Field(default=1, ge=1)
    reflection_pattern_min_evidence: int = Field(default=3, ge=2, le=100)
    reflection_pattern_min_days: int = Field(default=2, ge=2, le=365)
    reflection_auto_daily: bool = False
    reflection_auto_weekly: bool = False
    reflection_auto_monthly: bool = False
    reflection_notify: bool = False
    proactive_enabled: bool = True
    active_timeout_minutes: int = Field(default=20, ge=1, le=120)
    semi_active_timeout_minutes: int = Field(default=45, ge=1, le=240)
    away_idle_minutes: int = Field(default=30, ge=1, le=240)
    proactive_threshold_active: float = Field(default=.45, ge=0, le=1)
    proactive_threshold_semi_active: float = Field(default=.55, ge=0, le=1)
    proactive_threshold_idle: float = Field(default=.70, ge=0, le=1)
    proactive_heartbeat_seconds: int = Field(default=30, ge=5, le=300)
    proactive_cooldown_minutes: int = Field(default=45, ge=1, le=1440)
    proactive_natural_checkin_enabled: bool = True
    proactive_natural_checkin_min_hours: float = Field(default=3, ge=1, le=48)
    continuation_silence_minutes: int = Field(default=3, ge=2, le=5)
    continuation_cooldown_minutes: int = Field(default=5, ge=1, le=60)
    continuation_budget_per_active_window: int = Field(default=3, ge=1, le=3)
    proactive_event_buffer_seconds: int = Field(default=300, ge=0, le=600)
    proactive_db_path: str = ".zhaoxi/proactive.db"
    proactive_timezone: str = "Asia/Shanghai"
    proactive_max_events_per_tick: int = Field(default=50, ge=1, le=1000)
    proactive_misfire_grace_seconds: int = Field(default=3600, ge=0, le=604800)
    proactive_night_start_hour: int = Field(default=23, ge=0, le=23)
    proactive_night_end_hour: int = Field(default=8, ge=0, le=23)
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=4913, ge=1, le=65535)
    interface_settings_path: str = ".zhaoxi/interface-settings.json"
    session_db_path: str = ".zhaoxi/session.db"
    backup_directory: str = ".zhaoxi/backups"
    backup_retention_count: int = Field(default=14, ge=1, le=365)
    dev_browser_ui: bool = False
    desktop_geometry_path: str = ".zhaoxi/window-geometry.json"
    desktop_system_notifications: bool = False
    desktop_enabled: bool = True
    desktop_instance_path: str = ".zhaoxi/desktop-instance.json"
    desktop_activation_port: int = Field(default=4914, ge=1, le=65535)
    desktop_hotkey: str = "ctrl+alt+numpad0"
    desktop_companion_hotkey: str = "ctrl+alt+numpad1"
    desktop_window_width: int = Field(default=1080, ge=720, le=7680)
    desktop_window_height: int = Field(default=760, ge=520, le=4320)
    voice_enabled: bool = False
    voice_auto_send: bool = False
    voice_auto_speak: bool = False
    voice_language: str = "zh-CN"
    voice_max_seconds: float = Field(default=60, gt=0, le=300)
    voice_max_bytes: int = Field(default=4_194_304, ge=1024, le=100_000_000)
    voice_temp_dir: str = ".zhaoxi/tmp/voice"
    voice_device_name: str = ""
    stt_provider: str = "disabled"
    stt_base_url: str = ""
    stt_api_key: str = ""
    stt_model: str = ""
    stt_timeout_seconds: float = Field(default=45, gt=0, le=300)
    tts_provider: str = "windows"
    tts_voice: str = ""
    tts_rate: int = Field(default=0, ge=-10, le=10)
    tts_volume: int = Field(default=100, ge=0, le=100)
    tts_max_chars: int = Field(default=1200, ge=50, le=10_000)

    @model_validator(mode="after")
    def validate_planner_limits(self) -> "Settings":
        from zoneinfo import ZoneInfo
        legacy_memory_settings = {
            "memory_relevance_active_threshold": "memory_activation_active_threshold",
            "memory_relevance_forget_threshold": "memory_activation_dormant_threshold",
            "memory_relevance_decay_per_day": "memory_activation_decay_per_day",
            "memory_relevance_access_boost": "memory_activation_access_boost",
            "memory_cold_archive_after_days": "memory_cold_dormant_after_days",
        }
        for legacy, current in legacy_memory_settings.items():
            if legacy in self.model_fields_set and current not in self.model_fields_set:
                setattr(self, current, getattr(self, legacy))
        ZoneInfo(self.proactive_timezone)
        if ("request_finalization_reserve_tokens" in self.model_fields_set
                and self.request_finalization_reserve_tokens >= self.request_max_total_tokens):
            raise ValueError("收尾预算必须小于请求 Base Budget")
        if self.request_hard_limit_tokens is not None and self.request_hard_limit_tokens < self.request_max_total_tokens:
            raise ValueError("请求 Hard Limit 不能小于 Base Budget")
        if not self.proactive_threshold_active <= self.proactive_threshold_semi_active <= self.proactive_threshold_idle:
            raise ValueError("主动阈值必须满足 ACTIVE <= SEMI_ACTIVE <= IDLE")
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
        if self.retry_base_delay_seconds > self.retry_max_delay_seconds:
            raise ValueError("retry base delay 不能大于 max delay")
        fallback_values = {
            self.model_fallback_base_url,
            self.model_fallback_api_key,
            self.model_fallback_name,
        }
        if any(fallback_values) and not all(fallback_values):
            raise ValueError("fallback Provider 的 URL、API Key 和 Model 必须同时配置")
        if self.planner_max_attempts_per_step > self.planner_max_steps:
            raise ValueError("planner 每步尝试次数不能大于总执行步数")
        if self.memory_importance_forget_threshold >= self.memory_importance_keep_threshold:
            raise ValueError("memory importance 遗忘阈值必须低于保留阈值")
        if self.memory_relevance_forget_threshold >= self.memory_relevance_active_threshold:
            raise ValueError("memory relevance 遗忘阈值必须低于活跃阈值")
        if self.memory_activation_dormant_threshold >= self.memory_activation_active_threshold:
            raise ValueError("memory activation dormant 阈值必须低于 active 阈值")
        if self.memory_cold_dormant_after_days > self.memory_dormant_archive_after_days:
            raise ValueError("memory cold dormant 天数不能大于 dormant archive 天数")
        if self.memory_cluster_match_threshold >= self.memory_cluster_merge_threshold:
            raise ValueError("memory cluster match threshold 必须低于 merge threshold")
        if self.archive_chunk_overlap_chars >= self.archive_chunk_max_chars:
            raise ValueError("archive chunk overlap 必须小于 chunk max chars")
        if self.proactive_night_start_hour == self.proactive_night_end_hour:
            raise ValueError("proactive night 起止小时不能相同")
        if self.desktop_activation_port == self.web_port:
            raise ValueError("desktop activation port 不能与 web port 相同")
        from zhaoxi.desktop.hotkey import parse_hotkey

        parse_hotkey(self.desktop_hotkey)
        parse_hotkey(self.desktop_companion_hotkey)
        if self.stt_provider not in {"disabled", "openai-compatible"}:
            raise ValueError("stt provider 必须是 disabled 或 openai-compatible")
        if self.tts_provider not in {"disabled", "windows"}:
            raise ValueError("tts provider 必须是 disabled 或 windows")
        return self

    @property
    def request_budget_policy(self):
        from zhaoxi.reliability.retry import BudgetPolicy
        return BudgetPolicy(
            base_budget=self.request_max_total_tokens,
            extension_1_limit=self.request_extension_1_limit_tokens,
            extension_2_limit=self.request_extension_2_limit_tokens,
            hard_limit=self.request_hard_limit_tokens or min(
                10_000_000,
                self.request_max_total_tokens + self.request_extension_1_limit_tokens
                + self.request_extension_2_limit_tokens,
            ),
            finalization_reserve=(self.request_finalization_reserve_tokens
                                  if self.request_finalization_reserve_tokens < self.request_max_total_tokens
                                  else max(0, self.request_max_total_tokens // 5)),
            warning_ratio=self.request_budget_warning_ratio,
        )

    def validate_model_config(self) -> None:
        """Raise a readable error when required live-model settings are absent."""
        missing = []
        if not self.model_api_key:
            missing.append("ZHAOXI_MODEL_API_KEY")
        if not self.model_name:
            missing.append("ZHAOXI_MODEL_NAME")
        if missing:
            raise ConfigError(f"缺少模型配置：{', '.join(missing)}。请复制 .env.example 为 .env 后填写。")
