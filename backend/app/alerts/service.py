"""Dispatch alerts and escalate unacknowledged ones.

One scheduler loop owns a min-heap of (deadline, alert_id). Sending pushes a
deadline (O(log a)); the loop sleeps until the earliest deadline or until woken
by a new alert, and escalates whatever is due (O(log a) each). Acknowledged or
escalated alerts leave stale heap entries that are skipped when popped.
"""

import asyncio
import heapq
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from app.alerts.senders import AlertSender, AlertSendError
from app.cluster.service import IncidentService
from app.db import Database
from app.models import Alert, Contact, Incident
from app.ws import Broadcaster

log = logging.getLogger(__name__)


@dataclass
class _Live:
    alert: Alert
    message: str


def alert_message(incident: Incident) -> str:
    flags = " SILENT-SOS" if incident.silent_sos else ""
    hazards = f" Hazards: {', '.join(incident.linked_hazards)}." if incident.linked_hazards else ""
    return (
        f"SANKET{flags} sev {incident.severity}/5 · {incident.title} · "
        f"{incident.report_count} report(s).{hazards} Reply/ack on the board."
    )


class AlertService:
    def __init__(
        self,
        db: Database,
        incidents: IncidentService,
        broadcaster: Broadcaster,
        sender: AlertSender,
        contacts: dict[str, list[Contact]],
        ack_timeout_s: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self._incidents = incidents
        self._broadcaster = broadcaster
        self._sender = sender
        self._contacts = contacts
        self._timeout = ack_timeout_s
        self._clock = clock
        self._heap: list[tuple[float, str]] = []
        self._live: dict[str, _Live] = {}
        self._by_incident: dict[str, str] = {}
        self._alerted_department: dict[str, str] = {}
        self._wake = asyncio.Event()

    def _ladder(self, department: str) -> list[Contact]:
        return self._contacts.get(department) or self._contacts.get("none") or [Contact(name="Control room")]

    async def restore(self) -> int:
        """Resume escalation timers for alerts still waiting for an ack."""
        for alert in await self._db.unacknowledged_alerts():
            incident = await self._incidents.current(alert.incident_id)
            self._track(alert, alert_message(incident))
        return len(self._live)

    def _track(self, alert: Alert, message: str) -> None:
        self._alerted_department[alert.incident_id] = alert.department
        self._live[alert.id] = _Live(alert, message)
        self._by_incident[alert.incident_id] = alert.id
        heapq.heappush(self._heap, (alert.sent_at + self._timeout, alert.id))
        self._wake.set()

    async def dispatch(self, incident_id: str, triggered_by: str) -> Alert | None:
        """Alert the first contact for the incident's department; None if one is already live."""
        if incident_id in self._by_incident:
            return None
        incident = await self._incidents.current(incident_id)
        alert = await self._send(incident, level=0, triggered_by=triggered_by)
        updated = await self._incidents.set_status(incident_id, "dispatched", triggered_by, "dispatched")
        self._broadcaster.publish("incident.updated", updated.model_dump(mode="json"))
        return alert

    async def _send(self, incident: Incident, level: int, triggered_by: str, department: str | None = None) -> Alert:
        """Alert rung ``level`` of ``department``'s ladder (default: the incident's department).

        Escalations pass the original alert's department, so a later department change
        (LLM revision, dispatcher override) cannot point past the end of a shorter ladder.
        """
        department = department or incident.department
        contact = self._ladder(department)[level]
        message = alert_message(incident)
        channel = self._sender.channel
        try:
            await self._sender.send(contact, message)
        except AlertSendError as exc:
            log.error("alert to %s failed: %s", contact.name, exc)
            channel = f"{channel}:failed"
        alert = Alert(
            id=f"a_{uuid.uuid4().hex}",
            incident_id=incident.id,
            department=department,  # type: ignore[arg-type]
            channel=channel,
            contact=contact.name,
            level=level,
            sent_at=self._clock(),
            triggered_by=triggered_by,
        )
        async with self._db.transaction():
            await self._db.insert_alert(alert)
            await self._db.audit(
                [("alert", alert.id, "sent", triggered_by, None, alert.model_dump_json(include={"incident_id", "contact", "level", "channel"}))]
            )
        self._track(alert, message)
        self._broadcaster.publish("alert.sent", alert.model_dump(mode="json"))
        return alert

    async def reroute_if_department_changed(self, incident: Incident) -> Alert | None:
        """A dispatched incident whose department changed (LLM revision, override) alerts
        the newly responsible department too; a still-waiting alert to the old one stops
        escalating. O(log a)."""
        alerted = self._alerted_department.get(incident.id)
        if incident.status != "dispatched" or alerted is None or alerted == incident.department:
            return None
        alert_id = self._by_incident.pop(incident.id, None)
        if alert_id is not None:
            old = self._live.pop(alert_id).alert
            target = f"rerouted:{incident.department}"
            async with self._db.transaction():
                await self._db.update_alert(old.id, None, target)
                await self._db.audit([("alert", old.id, "rerouted", "department-change", alerted, incident.department)])
            self._broadcaster.publish("alert.updated", old.model_copy(update={"escalated_to": target}).model_dump(mode="json"))
        return await self._send(incident, level=0, triggered_by="department_changed")

    async def acknowledge(self, incident_id: str, actor: str) -> Alert:
        alert_id = self._by_incident.pop(incident_id, None)
        if alert_id is None:
            raise LookupError("no alert is waiting for acknowledgement")
        live = self._live.pop(alert_id)
        acked = live.alert.model_copy(update={"acknowledged_at": self._clock()})
        async with self._db.transaction():
            await self._db.update_alert(acked.id, acked.acknowledged_at, None)
            await self._db.audit([("alert", acked.id, "acknowledged", actor, None, None)])
        self._broadcaster.publish("alert.updated", acked.model_dump(mode="json"))
        return acked

    async def tick(self) -> list[Alert]:
        """Escalate every alert whose deadline passed. O(log a) per due entry."""
        now = self._clock()
        escalated: list[Alert] = []
        while self._heap and self._heap[0][0] <= now:
            _, alert_id = heapq.heappop(self._heap)
            live = self._live.pop(alert_id, None)
            if live is None:
                continue  # acknowledged or already escalated
            try:
                sent = await self._escalate(live.alert)
            except Exception:
                # One bad alert must not stop the others from escalating.
                log.exception("escalating alert %s failed", alert_id)
                continue
            if sent is not None:
                escalated.append(sent)
        return escalated

    async def _escalate(self, alert: Alert) -> Alert | None:
        self._by_incident.pop(alert.incident_id, None)
        ladder = self._ladder(alert.department)
        next_level = alert.level + 1
        target = ladder[next_level].name if next_level < len(ladder) else "exhausted"
        async with self._db.transaction():
            await self._db.update_alert(alert.id, None, target)
            await self._db.audit(
                [("alert", alert.id, "escalated", "escalation-timer", None, json.dumps({"to": target}))]
            )
        self._broadcaster.publish("alert.updated", alert.model_copy(update={"escalated_to": target}).model_dump(mode="json"))
        if next_level >= len(ladder):
            log.error("escalation ladder exhausted for incident %s", alert.incident_id)
            return None
        incident = await self._incidents.current(alert.incident_id)
        return await self._send(incident, next_level, "escalation", department=alert.department)

    async def run(self) -> None:
        """Sleep until the earliest deadline (or a new alert), then escalate what is due."""
        while True:
            timeout = max(0.0, self._heap[0][0] - self._clock()) if self._heap else None
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except TimeoutError:
                pass
            try:
                await self.tick()
            except Exception:
                log.exception("escalation tick failed")
