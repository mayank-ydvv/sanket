"""Pydantic schemas shared by every layer. All inter-layer data is validated here."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Department = Literal["fire", "police", "medical", "disaster", "utilities", "none"]
Channel = Literal["call", "sms", "web", "whatsapp"]
DecisionSource = Literal["local", "llm", "rules"]


class Decision(BaseModel):
    """Triage answer for one report. Strict: LLM output that does not match is rejected."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    is_emergency: bool
    emergency_prob: float = Field(ge=0.0, le=1.0)
    department: Department
    department_conf: float = Field(ge=0.0, le=1.0)
    severity: int = Field(ge=1, le=5)
    alert_now: bool
    location_text: str | None = None
    people_at_risk: str | None = None
    hazards: list[str] = Field(default_factory=list)
    silent_sos: bool = False
    prank_score: float = Field(0.0, ge=0.0, le=1.0)
    needs_human_review: bool = False


class DecisionResult(BaseModel):
    """A decision plus where it came from and how confident the producer was."""

    model_config = ConfigDict(frozen=True)

    decision: Decision
    source: DecisionSource
    confidence: float = Field(ge=0.0, le=1.0)


class ReportIn(BaseModel):
    """Body of ``POST /reports``. Empty text is allowed: it can be a silent SOS."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(max_length=4000)
    channel: Channel = "web"
    caller: str | None = Field(None, max_length=32)


class Report(BaseModel):
    """A stored report. ``caller_hash`` is a salted SHA-256; raw numbers are never kept."""

    id: str
    channel: Channel
    caller_hash: str | None
    raw_text: str
    received_at: float
    language: str | None = None
    english_gloss: str | None = None
    decision: Decision | None = None
    confidence: float | None = None
    incident_id: str | None = None
    flags: list[str] = Field(default_factory=list)
    source: DecisionSource | None = None
