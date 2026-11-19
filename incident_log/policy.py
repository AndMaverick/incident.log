"""Response targets per severity, and who gets pulled in as an incident ages."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import SEVERITIES, SLA_HOURS, Incident, deadline_after
from .scoring import Bands


def _check(table: dict[str, float], name: str) -> dict[str, float]:
    if set(table) != set(SEVERITIES) or any(v <= 0 for v in table.values()):
        raise ValueError(f"{name} needs a positive number of hours for each of {', '.join(SEVERITIES)}")
    return dict(table)


@dataclass
class Policy:
    """The targets an incident is held to. All times are hours of running clock from when the incident is opened.

    Defaults are a reasonable starting point for an AI service, not a standard. Set your own.
    """

    acknowledge_hours: dict[str, float] = field(default_factory=lambda: {"SEV1": 0.25, "SEV2": 1, "SEV3": 8, "SEV4": 24})
    mitigate_hours: dict[str, float] = field(default_factory=lambda: {"SEV1": 1, "SEV2": 8, "SEV3": 36, "SEV4": 120})
    resolve_hours: dict[str, float] = field(default_factory=lambda: dict(SLA_HOURS))
    # (share of the resolve target elapsed, role to notify), per severity, in order
    ladder: dict[str, list[tuple[float, str]]] = field(default_factory=lambda: {
        "SEV1": [(0.0, "on-call"), (0.25, "engineering lead"), (0.5, "executive sponsor")],
        "SEV2": [(0.0, "on-call"), (0.5, "engineering lead"), (0.9, "executive sponsor")],
        "SEV3": [(0.0, "owner"), (0.9, "engineering lead")],
        "SEV4": [(0.0, "owner")],
    })
    bands: Bands = field(default_factory=Bands)

    def __post_init__(self) -> None:
        self.acknowledge_hours = _check(self.acknowledge_hours, "acknowledge_hours")
        self.mitigate_hours = _check(self.mitigate_hours, "mitigate_hours")
        self.resolve_hours = _check(self.resolve_hours, "resolve_hours")
        for sev in SEVERITIES:
            if not self.acknowledge_hours[sev] <= self.mitigate_hours[sev] <= self.resolve_hours[sev]:
                raise ValueError(f"{sev}: acknowledge, mitigate and resolve targets must not decrease")

    def deadline(self, incident: Incident, stage: str) -> datetime | None:
        table = {"acknowledge": self.acknowledge_hours, "mitigate": self.mitigate_hours, "resolve": self.resolve_hours}[stage]
        return deadline_after(incident.opened, table[incident.severity], incident.pauses)

    def to_dict(self) -> dict[str, object]:
        return {"acknowledge_hours": self.acknowledge_hours, "mitigate_hours": self.mitigate_hours, "resolve_hours": self.resolve_hours,
                "ladder": {k: [list(x) for x in v] for k, v in self.ladder.items()},
                "bands": {"sev1": self.bands.sev1, "sev2": self.bands.sev2, "sev3": self.bands.sev3}}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Policy:
        raw_ladder = d.get("ladder")
        ladder = {k: [(float(a), str(b)) for a, b in v] for k, v in raw_ladder.items()} if isinstance(raw_ladder, dict) else None
        kwargs: dict[str, object] = {k: d[k] for k in ("acknowledge_hours", "mitigate_hours", "resolve_hours") if k in d}
        if ladder:
            kwargs["ladder"] = ladder
        if isinstance(d.get("bands"), dict):
            kwargs["bands"] = Bands(**d["bands"])  # type: ignore[arg-type]
        return cls(**kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Breach:
    incident: Incident
    stage: str  # acknowledge, mitigate or resolve
    deadline: datetime
    overdue: timedelta


@dataclass(frozen=True)
class Escalation:
    incident: Incident
    role: str
    due: datetime
