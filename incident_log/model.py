"""The records: incidents, their timeline, and the follow-up actions that stop them recurring."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

SLA_HOURS = {"SEV1": 4, "SEV2": 24, "SEV3": 72, "SEV4": 168}
SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")

# Failure modes specific to AI systems. "other" is always allowed, and any string is accepted, but these are the ones the
# reports group by.
CATEGORIES = ("hallucination", "prompt_injection", "data_leak", "pii_exposure", "bias", "drift", "outage", "latency",
              "cost_runaway", "tool_misuse", "safety_bypass", "compliance", "other")
DETECTED_BY = ("monitor", "eval", "user", "customer", "audit", "employee", "third_party", "unknown")
# Failure modes where the output itself was wrong or harmful, so the fix should leave behind a regression case.
OUTPUT_FAILURES = ("hallucination", "prompt_injection", "data_leak", "pii_exposure", "bias", "tool_misuse", "safety_bypass")
ACTION_KINDS = ("detection", "regression_case", "prevention", "process", "other")


@dataclass
class Event:
    at: datetime
    kind: str  # opened, acknowledged, mitigated, resolved, reopened, reclassified, escalated, paused, resumed, note, ...
    text: str = ""
    actor: str = ""


@dataclass
class Action:
    id: str
    text: str
    owner: str = ""
    due: datetime | None = None
    done: datetime | None = None
    kind: str = "other"
    ref: str = ""  # for a regression case, the id of the case in your eval suite

    def overdue(self, now: datetime) -> bool:
        return self.done is None and self.due is not None and now > self.due


@dataclass
class ObligationState:
    """A reporting duty that applies to one incident: when you became aware, and when (if ever) you filed."""

    key: str
    aware: datetime
    submitted: datetime | None = None
    note: str = ""


@dataclass
class Incident:
    id: str
    title: str
    score: int
    severity: str
    opened: datetime  # when the incident was recorded: the start of the response clock
    resolved: datetime | None = None
    cause: str = ""
    fix: str = ""
    category: str = "other"
    system: str = ""  # the product, model or pipeline affected
    description: str = ""
    impact: str = ""  # what happened to whom, in plain words
    occurred: datetime | None = None  # when it actually began, if known and earlier than ``opened``
    detected_by: str = "unknown"
    reporter: str = ""
    owner: str = ""
    customers_affected: int = 0
    personal_data: bool = False
    acknowledged: datetime | None = None
    mitigated: datetime | None = None
    tags: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    pauses: list[tuple[datetime, datetime | None]] = field(default_factory=list)  # SLA clock stopped, e.g. waiting on a customer
    obligations: dict[str, ObligationState] = field(default_factory=dict)
    reopened: int = 0
    initial_severity: str = ""

    def __post_init__(self) -> None:
        if not self.initial_severity:
            self.initial_severity = self.severity

    @property
    def deadline(self) -> datetime | None:
        """The resolve deadline under the default policy, extended by any time the clock was paused."""
        return deadline_after(self.opened, SLA_HOURS[self.severity], self.pauses)

    @property
    def is_open(self) -> bool:
        return self.resolved is None

    def hours_to(self, end: datetime | None, start: datetime | None = None) -> float | None:
        if end is None:
            return None
        return (end - (start or self.opened)).total_seconds() / 3600


def deadline_after(start: datetime, hours: float, pauses: list[tuple[datetime, datetime | None]]) -> datetime | None:
    """``start`` plus ``hours`` of running clock. Time inside a pause does not count, and an open pause means no deadline."""
    end = start + timedelta(hours=hours)
    for p0, p1 in sorted(pauses, key=lambda p: p[0]):
        if p0 >= end:
            break
        if p1 is None:
            return None
        end += p1 - max(p0, start)
    return end
