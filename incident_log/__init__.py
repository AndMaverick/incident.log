"""incident.log: an AI incident register with risk scoring, SLA tracking, and postmortems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

__version__ = "0.1.0"

SLA_HOURS = {"SEV1": 4, "SEV2": 24, "SEV3": 72, "SEV4": 168}


def risk_score(impact: int, likelihood: int, detectability: int) -> int:
    """Each factor is 1 to 5. High detectability lowers risk: 5 means it is caught fast."""
    for name, value in (("impact", impact), ("likelihood", likelihood), ("detectability", detectability)):
        if not 1 <= value <= 5:
            raise ValueError(f"{name} must be 1 to 5")
    return impact * likelihood * (6 - detectability)


def severity(score: int) -> str:
    if score >= 60:
        return "SEV1"
    if score >= 30:
        return "SEV2"
    if score >= 12:
        return "SEV3"
    return "SEV4"


@dataclass
class Incident:
    id: str
    title: str
    score: int
    severity: str
    opened: datetime
    resolved: datetime | None = None
    cause: str = ""
    fix: str = ""

    @property
    def deadline(self) -> datetime:
        return self.opened + timedelta(hours=SLA_HOURS[self.severity])


class Register:
    def __init__(self) -> None:
        self.incidents: dict = {}

    def open(self, id: str, title: str, impact: int, likelihood: int, detectability: int,
             when: datetime) -> Incident:
        if id in self.incidents:
            raise ValueError(f"incident exists: {id}")
        score = risk_score(impact, likelihood, detectability)
        incident = Incident(id, title, score, severity(score), when)
        self.incidents[id] = incident
        return incident

    def resolve(self, id: str, when: datetime, cause: str = "", fix: str = "") -> Incident:
        incident = self.incidents[id]
        incident.resolved, incident.cause, incident.fix = when, cause, fix
        return incident

    def breached(self, now: datetime) -> list:
        """Unresolved incidents past their SLA deadline, most severe first."""
        late = [i for i in self.incidents.values() if i.resolved is None and now > i.deadline]
        return sorted(late, key=lambda i: (i.severity, i.opened))

    def mttr_hours(self):
        done = [i for i in self.incidents.values() if i.resolved]
        if not done:
            return None
        return sum((i.resolved - i.opened).total_seconds() for i in done) / len(done) / 3600

    def postmortem(self, id: str) -> str:
        i = self.incidents[id]
        status = f"resolved {i.resolved:%Y-%m-%d %H:%M}" if i.resolved else "open"
        return "\n".join([
            f"# Postmortem: {i.title}", "",
            f"- ID: {i.id}", f"- Severity: {i.severity} (risk score {i.score})",
            f"- Opened: {i.opened:%Y-%m-%d %H:%M}", f"- Status: {status}", "",
            "## Cause", i.cause or "_to be completed_", "",
            "## Fix", i.fix or "_to be completed_", "",
            "## Follow-ups", "- [ ] Add a detection for this failure mode", "- [ ] Add a regression case to the eval suite",
        ])
