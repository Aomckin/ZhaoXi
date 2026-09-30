"""Tunable confidence thresholds for the local Fast Gate."""
from pydantic import BaseModel, Field


class FastGateConfig(BaseModel):
    strong_threshold: float = Field(default=0.8, gt=0, le=1)
    conversation_threshold: float = Field(default=0.75, gt=0, le=1)
    relevance_threshold: float = Field(default=0.35, gt=0, le=1)
    sufficiency_threshold: float = Field(default=0.55, gt=0, le=1)
    risk_ceiling: float = Field(default=0.3, ge=0, lt=1)
    fast_min_score: float = Field(default=0.75, gt=0, le=1)
    fast_min_positive_votes: int = Field(default=4, ge=1, le=7)
