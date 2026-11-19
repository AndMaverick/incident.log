"""JSON form of a register: every datetime as ISO 8601, every field kept."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .model import Action, Event, Incident, ObligationState
from .policy import Policy

if TYPE_CHECKING:
    from .register import Register

VERSION = 1


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def incident_to_dict(i: Incident) -> dict[str, Any]:
    return {
        "id": i.id, "title": i.title, "score": i.score, "severity": i.severity, "initial_severity": i.initial_severity,
        "opened": _dt(i.opened), "resolved": _dt(i.resolved), "cause": i.cause, "fix": i.fix, "category": i.category,
        "system": i.system, "description": i.description, "impact": i.impact, "occurred": _dt(i.occurred),
        "detected_by": i.detected_by, "reporter": i.reporter, "owner": i.owner, "customers_affected": i.customers_affected,
        "personal_data": i.personal_data, "acknowledged": _dt(i.acknowledged), "mitigated": _dt(i.mitigated), "tags": i.tags,
        "reopened": i.reopened,
        "events": [{"at": _dt(e.at), "kind": e.kind, "text": e.text, "actor": e.actor} for e in i.events],
        "actions": [{"id": a.id, "text": a.text, "owner": a.owner, "due": _dt(a.due), "done": _dt(a.done), "kind": a.kind, "ref": a.ref}
                    for a in i.actions],
        "pauses": [[_dt(a), _dt(b)] for a, b in i.pauses],
        "obligations": {k: {"aware": _dt(s.aware), "submitted": _dt(s.submitted), "note": s.note} for k, s in i.obligations.items()},
    }


def incident_from_dict(d: dict[str, Any]) -> Incident:
    opened = _parse(d["opened"])
    assert opened is not None
    i = Incident(d["id"], d["title"], d["score"], d["severity"], opened, _parse(d.get("resolved")), d.get("cause", ""), d.get("fix", ""),
                 d.get("category", "other"), d.get("system", ""), d.get("description", ""), d.get("impact", ""), _parse(d.get("occurred")),
                 d.get("detected_by", "unknown"), d.get("reporter", ""), d.get("owner", ""), d.get("customers_affected", 0),
                 d.get("personal_data", False), _parse(d.get("acknowledged")), _parse(d.get("mitigated")), list(d.get("tags", [])),
                 reopened=d.get("reopened", 0), initial_severity=d.get("initial_severity", ""))
    i.events = [Event(_parse(e["at"]), e["kind"], e.get("text", ""), e.get("actor", "")) for e in d.get("events", [])]  # type: ignore[arg-type]
    i.actions = [Action(a["id"], a["text"], a.get("owner", ""), _parse(a.get("due")), _parse(a.get("done")), a.get("kind", "other"), a.get("ref", ""))
                 for a in d.get("actions", [])]
    i.pauses = [(_parse(a), _parse(b)) for a, b in d.get("pauses", [])]  # type: ignore[misc]
    i.obligations = {k: ObligationState(k, _parse(s["aware"]), _parse(s.get("submitted")), s.get("note", ""))  # type: ignore[arg-type]
                     for k, s in d.get("obligations", {}).items()}
    return i


def register_to_dict(r: Register) -> dict[str, Any]:
    return {"version": VERSION, "policy": r.policy.to_dict(), "incidents": [incident_to_dict(i) for i in r.incidents.values()]}


def register_from_dict(data: dict[str, Any]) -> Register:
    from .register import Register
    if data.get("version") != VERSION:
        raise ValueError(f"unsupported register version {data.get('version')!r}")
    reg = Register(Policy.from_dict(data["policy"]) if data.get("policy") else None)
    for d in data.get("incidents", []):
        i = incident_from_dict(d)
        reg.incidents[i.id] = i
    return reg
