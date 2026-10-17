"""Pydantic schemas shared by every layer. All inter-layer data is validated here."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

Department = Literal["fire", "police", "medical", "disaster", "utilities", "none"]
Channel = Literal["call", "sms", "web", "whatsapp"]
DecisionSource = Literal["local", "llm", "rules"]
Lane = Literal["auto", "confirm", "review"]

AUTO_DISPATCH_CONF = 0.9
REVIEW_BELOW_CONF = 0.5


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


    @property
    def confidence(self) -> float:
        """The weaker of the emergency call (either way) and the department call."""
        return min(max(self.emergency_prob, 1.0 - self.emergency_prob), self.department_conf)

    @property
    def lane(self) -> Lane:
        """Confidence gate: auto-dispatch, one-click confirm, or the human review lane."""
        if self.needs_human_review or self.silent_sos or self.confidence < REVIEW_BELOW_CONF:
            return "review"
        if (
            self.is_emergency
            and self.emergency_prob >= AUTO_DISPATCH_CONF
            and self.department_conf >= AUTO_DISPATCH_CONF
        ):
            return "auto"
        return "confirm"


class DecisionResult(BaseModel):
    """A decision plus who produced it, how confident it was and which rules fired."""

    model_config = ConfigDict(frozen=True)

    decision: Decision
    source: DecisionSource
    confidence: float = Field(ge=0.0, le=1.0)
    model: str
    prompt_version: str | None = None
    rules_fired: list[str] = Field(default_factory=list)


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
    location_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    refining: bool = False  # true while the fast LLM is re-checking an uncertain decision

    @computed_field  # type: ignore[prop-decorator]
    @property
    def lane(self) -> Lane | None:
        return self.decision.lane if self.decision else None


IncidentStatus = Literal["open", "dispatched", "resolved", "merged"]


class Incident(BaseModel):
    """A cluster of reports about one event, as stored and broadcast."""

    id: str
    title: str
    department: Department
    severity: int = Field(ge=1, le=5)
    status: IncidentStatus
    lat: float | None
    lng: float | None
    location_text: str | None
    location_confirmed: bool
    report_count: int
    first_seen: float
    last_updated: float
    linked_hazards: list[str] = Field(default_factory=list)
    briefing: list[str] | None = None
    lane: Lane = "confirm"
    confidence: float = 0.0
    silent_sos: bool = False
    prank_suspected: bool = False
    needs_review: bool = False
    overrides: dict[str, str | int] = Field(default_factory=dict)


class Price(BaseModel):
    """US dollars per million tokens."""

    input: float
    output: float


class Contact(BaseModel):
    """One rung of a department's escalation ladder (station first, supervisor last)."""

    name: str
    phone: str | None = None


class Alert(BaseModel):
    id: str
    incident_id: str
    department: Department
    channel: str
    contact: str
    level: int
    sent_at: float
    acknowledged_at: float | None = None
    escalated_to: str | None = None
    triggered_by: str


class OverrideRequest(BaseModel):
    """Dispatcher correction; stored in the audit log as a future training label."""

    model_config = ConfigDict(extra="forbid")

    department: Department | None = None
    severity: int | None = Field(None, ge=1, le=5)
    note: str | None = Field(None, max_length=500)


class AuditEntry(BaseModel):
    action: str
    actor: str
    before: str | None
    after: str | None
    at: float


class IncidentDetail(BaseModel):
    incident: Incident
    reports: list[Report]
    audit: list[AuditEntry]
    alerts: list[Alert] = Field(default_factory=list)
