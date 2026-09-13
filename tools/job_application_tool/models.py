"""Validated public models for the JobApplication tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectPageInput(StrictModel):
    include_options: bool = True


class BuildPlanInput(StrictModel):
    inspection_id: str = Field(min_length=8, max_length=160)
    profile_id: str | None = Field(default=None, max_length=160)
    allow_ai_mapping: bool = False


class ApplySafeFieldsInput(StrictModel):
    plan_id: str = Field(pattern=r"^jap_[A-Za-z0-9_-]{16,160}$")
    expected_page_fingerprint: str = Field(min_length=16, max_length=160)
    expected_profile_revision: int = Field(ge=0)


class GetReviewInput(StrictModel):
    plan_id: str = Field(pattern=r"^jap_[A-Za-z0-9_-]{16,160}$")
    show_overlay: bool = True


class GetProfileInput(StrictModel):
    profile_id: str | None = Field(default=None, max_length=160)
    mode: Literal["summary", "section", "field_metadata"] = "summary"
    section: str | None = Field(default=None, max_length=120)


class ProfilePatch(StrictModel):
    path: str = Field(min_length=1, max_length=240)
    value: Any

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        if value.startswith("_") or "__" in value or any(part in {"prototype", "constructor"} for part in value.split(".")):
            raise ValueError("unsafe profile path")
        return value


class UpdateProfileInput(StrictModel):
    profile_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0)
    patches: list[ProfilePatch] = Field(min_length=1, max_length=50)


class BridgeResponse(StrictModel):
    protocol: str
    version: int
    request_id: str
    ok: bool
    data: Any = None
    error: str | None = None
