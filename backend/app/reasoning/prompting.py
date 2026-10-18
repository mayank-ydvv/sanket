"""System 2 prompt input and strict, grounded parsing of the reasoning model's answer."""

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.models import Incident, Report

REASONING_PROMPT_VERSION = "reasoning_v1"
MAX_HAZARDS = 8
MAX_HAZARD_CHARS = 40
MAX_RISK_CHARS = 220
MAX_BRIEFING_LINES = 3
MAX_LINE_CHARS = 200
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ReasoningOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    linked_hazards: list[str] = []
    combined_risk: str | None = None
    merge_suggestions: list[str] = []
    briefing: list[str] = []


def _clean(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def parse_reasoning(text: str, allowed_merge_ids: set[str]) -> ReasoningOutput | None:
    """Validate and ground the model's JSON. O(L).

    Merge suggestions are kept only if they name a nearby incident we actually
    showed the model; hazards and briefing lines are de-duplicated and capped.
    """
    try:
        payload: Any = json.loads(_FENCE.sub("", text.strip()))
        raw = ReasoningOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError):
        return None
    hazards = list(dict.fromkeys(_clean(h, MAX_HAZARD_CHARS).lower() for h in raw.linked_hazards if h.strip()))
    risk = _clean(raw.combined_risk, MAX_RISK_CHARS) if raw.combined_risk else None
    if risk and risk.lower().rstrip(".") in {"none", "null", "n/a", "no combined risk"}:
        risk = None
    briefing = [_clean(line, MAX_LINE_CHARS) for line in raw.briefing if line.strip()][:MAX_BRIEFING_LINES]
    return ReasoningOutput(
        linked_hazards=hazards[:MAX_HAZARDS],
        combined_risk=risk,
        merge_suggestions=[i for i in dict.fromkeys(raw.merge_suggestions) if i in allowed_merge_ids],
        briefing=briefing,
    )


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes} min ago" if minutes else "just now"


def build_message(
    incident: Incident,
    reports: Sequence[Report],
    nearby: Sequence[tuple[Incident, float, Sequence[str]]],
    now: float,
) -> str:
    """Compact, numbered prompt input. O(total text)."""
    location = incident.location_text or "not stated"
    confirmed = "confirmed" if incident.location_confirmed else "unconfirmed"
    lines = [
        f"INCIDENT {incident.id} | department {incident.department} | severity {incident.severity}/5 | "
        f"location: {location} ({confirmed}) | {incident.report_count} reports",
        "REPORTS (oldest first):",
    ]
    for i, report in enumerate(reports, 1):
        text = " ".join(report.raw_text.split()) or "(silent call: no words)"
        lines.append(f"[{i}] ({report.channel}, {_ago(now - report.received_at)}) {text}")
    if nearby:
        lines.append("NEARBY INCIDENTS (within 300 m, last 15 min):")
        for other, distance_m, samples in nearby:
            quoted = "; ".join(f'"{" ".join(s.split())[:160]}"' for s in samples)
            hazards = ", ".join(other.linked_hazards) or "none listed"
            lines.append(
                f"- {other.id} | {other.department} | {other.location_text or 'unlocated'} | "
                f"{distance_m:.0f} m | hazards: {hazards} | e.g. {quoted}"
            )
    else:
        lines.append("NEARBY INCIDENTS: none")
    return "\n".join(lines)
