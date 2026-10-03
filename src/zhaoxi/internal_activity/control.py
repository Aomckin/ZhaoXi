"""Validated, persistent controls layered over startup defaults."""
from __future__ import annotations
import json
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from .models import PresenceState

class PresenceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    active_hold_seconds: float = Field(default=1200, ge=5, le=7200)
    semi_active_hold_seconds: float = Field(default=2700, ge=5, le=21600)
    heartbeat_enabled: StrictBool = True
    heartbeat_interval_seconds: float = Field(default=30, ge=5, le=1800)
    heartbeat_multipliers: dict[PresenceState, float] = Field(default_factory=lambda: {p: 1 for p in PresenceState})
    sleep_enabled: StrictBool = False
    sleep_start_hour: int = Field(default=0, ge=0, le=23)
    sleep_end_hour: int = Field(default=7, ge=0, le=23)

class ActivityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: StrictBool = True
    priority: int = Field(default=50, ge=0, le=100)
    min_interval_minutes: float = Field(default=30, ge=0, le=10080)
    daily_budget: int = Field(default=1000000, ge=0, le=1000000)
    presence_policy: dict[PresenceState, Literal["AUTO", "MANUAL_ONLY", "DISABLED"]] = Field(default_factory=dict)

class ActivitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = True
    max_activities_per_tick: int = Field(default=20, ge=0, le=30)
    max_llm_per_tick: int = Field(default=1, ge=0, le=4)
    max_local_per_tick: int = Field(default=3, ge=0, le=10)
    max_llm_light_per_tick: int = Field(default=1, ge=0, le=4)
    max_llm_heavy_per_tick: int = Field(default=0, ge=0, le=4)
    max_external_read_per_tick: int = Field(default=1, ge=0, le=10)
    max_external_write_per_tick: int = Field(default=1, ge=0, le=4)
    daily_llm_budget: int = Field(default=1000000, ge=0, le=1000000)
    daily_external_read_budget: int = Field(default=1000000, ge=0, le=1000000)
    daily_external_write_budget: int = Field(default=1000000, ge=0, le=1000000)
    social_lurk_enabled: StrictBool = False
    social_wander_enabled: StrictBool = False
    social_allowed_groups: list[str] = Field(default_factory=list, max_length=100)
    social_group_cooldown_minutes: int = Field(default=45, ge=1, le=10080)
    social_daily_message_limit: int = Field(default=6, ge=0, le=100)

class RuntimeControl:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = runtime.path.with_name(runtime.path.stem + "-settings.json")
        s = runtime.settings
        from zhaoxi.config.settings import Settings
        get = lambda key: getattr(s, key, Settings.model_fields[key].get_default(call_default_factory=True))
        self.defaults = {
            "presence": PresenceSettings(active_hold_seconds=get("active_timeout_minutes") * 60,
                semi_active_hold_seconds=get("semi_active_timeout_minutes") * 60,
                heartbeat_interval_seconds=get("proactive_heartbeat_seconds"),
                sleep_enabled=get("presence_sleep_enabled"), sleep_start_hour=get("presence_sleep_start_hour"),
                sleep_end_hour=get("presence_sleep_end_hour")).model_dump(mode="json"),
            "activity": ActivitySettings(enabled=s.internal_activity_enabled,
                **{key: get("internal_activity_" + key) for key in
                   ("max_llm_per_tick", "max_local_per_tick", "max_llm_light_per_tick", "max_llm_heavy_per_tick",
                    "max_external_read_per_tick", "max_external_write_per_tick")},
                social_lurk_enabled=get("social_lurk_enabled"), social_wander_enabled=get("social_wander_enabled"),
                social_allowed_groups=get("social_wander_qq_allowed_groups"),
                social_group_cooldown_minutes=get("social_wander_group_cooldown_minutes"),
                social_daily_message_limit=get("social_wander_daily_message_limit")).model_dump(mode="json"),
            "configs": {spec.name: ActivityConfig(enabled=runtime._enabled(spec.name), priority=spec.priority,
                min_interval_minutes=spec.min_interval,
                daily_budget=getattr(s, spec.daily_limit_setting, 1000000) if spec.daily_limit_setting else 1000000,
                presence_policy={p: "AUTO" if p in spec.presence_states else "DISABLED" for p in PresenceState}).model_dump(mode="json")
                for spec in runtime.registry},
        }
        self.saved = {"presence": {}, "activity": {}, "configs": {}}
        self.changed = asyncio.Event()
        self.next_tick_at = None
        self.debug_override = None
        self.load_error = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for section, cls in (("presence", PresenceSettings), ("activity", ActivitySettings)):
                    cls.model_validate({**self.defaults[section], **data.get(section, {})})
                for name, config in data.get("configs", {}).items():
                    if name in self.defaults["configs"]:
                        ActivityConfig.model_validate({**self.defaults["configs"][name], **config})
                self._validate_presence({**self.defaults["presence"], **data.get("presence", {})})
                self.saved = {k: data.get(k, {}) for k in self.saved}
            except (OSError, ValueError, TypeError, AttributeError):
                self.load_error = "持久配置无法读取，当前使用启动默认值。"
        self.apply()

    @staticmethod
    def _validate_presence(value):
        multipliers = value["heartbeat_multipliers"]
        if set(multipliers) != set(PresenceState) or any(not 1 <= x <= 60 for x in multipliers.values()):
            raise ValueError("Heartbeat 倍率须覆盖五态且处于 1–60")

    def presence(self):
        return {**self.defaults["presence"], **self.saved["presence"], **(self.debug_override or {})}

    def activity(self):
        return {**self.defaults["activity"], **self.saved["activity"]}

    def config(self, name):
        if name not in self.defaults["configs"]:
            spec = self.runtime.registry.get(name)
            self.defaults["configs"][name] = ActivityConfig(enabled=bool(getattr(self.runtime.settings,spec.enabled_setting,False)) if spec.enabled_setting else True, priority=spec.priority,
                min_interval_minutes=spec.min_interval, presence_policy={p:"AUTO" if p in spec.presence_states else "DISABLED" for p in PresenceState}).model_dump(mode="json")
        return {**self.defaults["configs"][name], **self.saved["configs"].get(name, {})}

    def update(self, section, value, *, name=None, reset=False):
        import copy
        candidate = copy.deepcopy(self.saved)
        if section == "configs":
            validated = ActivityConfig.model_validate({**self.config(name), **value}).model_dump(mode="json")
            if set(validated["presence_policy"]) != set(PresenceState):
                raise ValueError("活动权限须覆盖五态")
            candidate[section][name] = {} if reset else validated
        else:
            cls = PresenceSettings if section == "presence" else ActivitySettings
            validated = cls.model_validate({**self.defaults[section], **candidate[section], **value}).model_dump(mode="json")
            if section == "presence":
                self._validate_presence(validated)
            if section == "activity" and any(not g.isdigit() or not 1 <= len(g) <= 20 for g in validated["social_allowed_groups"]):
                raise ValueError("授权群须为数字群号")
            candidate[section] = {} if reset else validated
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        self.saved = candidate
        self.apply()

    def apply(self):
        self.changed.set()
        p, a, s = self.presence(), self.activity(), self.runtime.settings
        s.proactive_heartbeat_seconds = p["heartbeat_interval_seconds"]
        s.presence_sleep_enabled = p["sleep_enabled"]
        s.presence_sleep_start_hour, s.presence_sleep_end_hour = p["sleep_start_hour"], p["sleep_end_hour"]
        s.internal_activity_enabled = a["enabled"]
        for key in ("max_llm_per_tick", "max_local_per_tick", "max_llm_light_per_tick", "max_llm_heavy_per_tick", "max_external_read_per_tick", "max_external_write_per_tick"):
            setattr(s, "internal_activity_" + key, a[key])
        s.social_lurk_enabled, s.social_wander_enabled = a["social_lurk_enabled"], a["social_wander_enabled"]
        s.social_wander_qq_allowed_groups = a["social_allowed_groups"]
        s.social_wander_group_cooldown_minutes = a["social_group_cooldown_minutes"]
        s.social_wander_daily_message_limit = a["social_daily_message_limit"]
        interaction = getattr(getattr(self.runtime.agent, "proactive_state", None), "interaction", None)
        if interaction:
            interaction.set_timing(p["active_hold_seconds"], p["semi_active_hold_seconds"])
        heartbeat = getattr(self.runtime.agent, "proactive_heartbeat", None)
        if heartbeat:
            heartbeat.control = self
            heartbeat.control_changed.set()

    def interval(self):
        p = self.presence()
        return min(1800, p["heartbeat_interval_seconds"] * p["heartbeat_multipliers"][self.runtime.presence().value])

    async def wait_interval(self):
        while True:
            self.changed.clear()
            interval = self.interval()
            self.next_tick_at = datetime.now(UTC) + timedelta(seconds=interval) if self.presence()["heartbeat_enabled"] else None
            try:
                await asyncio.wait_for(self.changed.wait(), interval)
            except TimeoutError:
                return

    def snapshot(self, section):
        return {"values": self.presence() if section == "presence" else self.activity(),
                "defaults": self.defaults[section], "modified": bool(self.saved[section]),
                "debug_override": self.debug_override, "storage": str(self.path),
                "effective": "立即生效；Heartbeat 从本次保存重新计时，活动参数下次候选检查生效。",
                "load_error": self.load_error}
