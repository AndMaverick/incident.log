"""The register: open an incident, move it through its life, and ask what is late, who to call, and what is owed to regulators."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .model import ACTION_KINDS, SEVERITIES, Action, Event, Incident, ObligationState, deadline_after
from .obligations import OBLIGATIONS, Obligation
from .policy import Breach, Escalation, Policy
from .scoring import risk_score


@dataclass(frozen=True)
class Due:
    """A reporting duty on an incident, with where it stands."""

    incident: Incident
    obligation: Obligation
    deadline: datetime
    submitted: datetime | None
    status: str  # open, overdue, filed, filed late

    def remaining(self, now: datetime) -> timedelta:
        return self.deadline - (self.submitted or now)


class Register:
    def __init__(self, policy: Policy | None = None) -> None:
        self.incidents: dict[str, Incident] = {}
        self.policy = policy or Policy()
        self.obligation_defs: dict[str, Obligation] = dict(OBLIGATIONS)

    # ------------------------------------------------------------------------------------------------------- helpers
    def get(self, id: str) -> Incident:
        try:
            return self.incidents[id]
        except KeyError:
            raise KeyError(f"no incident {id!r}") from None

    @staticmethod
    def _log(i: Incident, at: datetime, kind: str, text: str = "", actor: str = "") -> None:
        i.events.append(Event(at, kind, text, actor))

    @staticmethod
    def _not_before_open(i: Incident, when: datetime, what: str) -> None:
        if when < i.opened:
            raise ValueError(f"{what} ({when}) is before the incident was opened ({i.opened})")

    # ----------------------------------------------------------------------------------------------------- lifecycle
    def open(self, id: str, title: str, impact: int, likelihood: int, detectability: int, when: datetime, *,
             category: str = "other", system: str = "", description: str = "", occurred: datetime | None = None,
             detected_by: str = "unknown", reporter: str = "", owner: str = "", customers_affected: int = 0,
             personal_data: bool = False, tags: Iterable[str] = ()) -> Incident:
        if id in self.incidents:
            raise ValueError(f"incident exists: {id}")
        if occurred is not None and occurred > when:
            raise ValueError("an incident cannot occur after it was opened")
        if customers_affected < 0:
            raise ValueError("customers_affected cannot be negative")
        score = risk_score(impact, likelihood, detectability)
        i = Incident(id, title, score, self.policy.bands.severity(score), when, category=category, system=system,
                     description=description, occurred=occurred, detected_by=detected_by, reporter=reporter, owner=owner,
                     customers_affected=customers_affected, personal_data=personal_data, tags=list(tags))
        self._log(i, when, "opened", f"{i.severity}, risk score {score}", reporter)
        self.incidents[id] = i
        return i

    def acknowledge(self, id: str, when: datetime, by: str = "") -> Incident:
        i = self.get(id)
        self._not_before_open(i, when, "acknowledgement")
        if i.acknowledged is None:
            i.acknowledged = when
            self._log(i, when, "acknowledged", actor=by)
        return i

    def mitigate(self, id: str, when: datetime, note: str = "", by: str = "") -> Incident:
        i = self.get(id)
        self._not_before_open(i, when, "mitigation")
        if i.mitigated is None:
            i.mitigated = when
            self._log(i, when, "mitigated", note, by)
        return i

    def resolve(self, id: str, when: datetime, cause: str = "", fix: str = "", by: str = "") -> Incident:
        i = self.get(id)
        self._not_before_open(i, when, "resolution")
        i.resolved, i.cause, i.fix = when, cause, fix
        self._log(i, when, "resolved", cause, by)
        return i

    def reopen(self, id: str, when: datetime, reason: str = "") -> Incident:
        i = self.get(id)
        if i.resolved is None:
            raise ValueError(f"{id} is not resolved")
        i.resolved = None
        i.reopened += 1
        self._log(i, when, "reopened", reason)
        return i

    def reclassify(self, id: str, severity: str, when: datetime, reason: str = "", by: str = "") -> Incident:
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        i = self.get(id)
        self._log(i, when, "reclassified", f"{i.severity} -> {severity}. {reason}".strip(), by)
        i.severity = severity
        return i

    def pause(self, id: str, when: datetime, reason: str = "") -> Incident:
        """Stop the response clock, for example while waiting on the customer. Time paused does not count against any target."""
        i = self.get(id)
        if i.pauses and i.pauses[-1][1] is None:
            raise ValueError(f"{id} is already paused")
        i.pauses.append((when, None))
        self._log(i, when, "paused", reason)
        return i

    def resume(self, id: str, when: datetime) -> Incident:
        i = self.get(id)
        if not i.pauses or i.pauses[-1][1] is not None:
            raise ValueError(f"{id} is not paused")
        start = i.pauses[-1][0]
        if when < start:
            raise ValueError("cannot resume before the pause began")
        i.pauses[-1] = (start, when)
        self._log(i, when, "resumed")
        return i

    def note(self, id: str, when: datetime, text: str, by: str = "") -> Incident:
        i = self.get(id)
        self._log(i, when, "note", text, by)
        return i

    # ------------------------------------------------------------------------------------------------------- actions
    def add_action(self, id: str, text: str, owner: str = "", due: datetime | None = None, kind: str = "other", ref: str = "") -> Action:
        if kind not in ACTION_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ACTION_KINDS)}")
        i = self.get(id)
        action = Action(f"A{len(i.actions) + 1}", text, owner, due, None, kind, ref)
        i.actions.append(action)
        return action

    def complete_action(self, id: str, action_id: str, when: datetime) -> Action:
        for a in self.get(id).actions:
            if a.id == action_id:
                a.done = when
                return a
        raise KeyError(f"no action {action_id!r} on {id}")

    # ------------------------------------------------------------------------------------------ clocks and escalation
    def breaches(self, now: datetime) -> list[Breach]:
        """Every response target an open incident has missed so far, most severe and most overdue first."""
        out: list[Breach] = []
        for i in self.incidents.values():
            if i.resolved is not None:
                continue
            for stage, done in (("acknowledge", i.acknowledged), ("mitigate", i.mitigated), ("resolve", None)):
                if done is not None:
                    continue
                d = self.policy.deadline(i, stage)
                if d is not None and now > d:
                    out.append(Breach(i, stage, d, now - d))
        return sorted(out, key=lambda b: (b.incident.severity, -b.overdue.total_seconds(), b.incident.id))

    def breached(self, now: datetime) -> list[Incident]:
        """Unresolved incidents past their resolve deadline, most severe first."""
        late = [i for i in self.incidents.values() if i.resolved is None and (d := self.policy.deadline(i, "resolve")) is not None and now > d]
        return sorted(late, key=lambda i: (i.severity, i.opened))

    def escalations(self, now: datetime) -> list[Escalation]:
        """People who should be told by now and have not been, per the policy ladder. Stops once an incident is mitigated."""
        out: list[Escalation] = []
        for i in self.incidents.values():
            if i.resolved is not None or i.mitigated is not None:
                continue
            told = {e.text for e in i.events if e.kind == "escalated"}
            hours = self.policy.resolve_hours[i.severity]
            for fraction, role in self.policy.ladder.get(i.severity, []):
                due = deadline_after(i.opened, fraction * hours, i.pauses) if fraction > 0 else i.opened
                if due is not None and due <= now and role not in told:
                    out.append(Escalation(i, role, due))
        return sorted(out, key=lambda e: (e.incident.severity, e.due))

    def escalate(self, id: str, when: datetime, role: str, by: str = "") -> Incident:
        i = self.get(id)
        self._log(i, when, "escalated", role, by)
        return i

    # ----------------------------------------------------------------------------------------------- regulatory clocks
    def define_obligation(self, obligation: Obligation) -> None:
        """Add your own reporting duty (a sector rule, a contract clause) next to the built-in ones."""
        self.obligation_defs[obligation.key] = obligation

    def track(self, id: str, key: str, aware: datetime | None = None, note: str = "") -> ObligationState:
        """Start a reporting clock on an incident from the moment you became aware. When that is, is a legal question."""
        if key not in self.obligation_defs:
            raise KeyError(f"unknown obligation {key!r}; known: {', '.join(sorted(self.obligation_defs))}")
        i = self.get(id)
        state = ObligationState(key, aware or i.opened, None, note)
        i.obligations[key] = state
        self._log(i, state.aware, "obligation_started", f"{key}: {self.obligation_defs[key].label}")
        return state

    def submit(self, id: str, key: str, when: datetime) -> ObligationState:
        i = self.get(id)
        if key not in i.obligations:
            raise KeyError(f"{key} is not being tracked on {id}")
        i.obligations[key].submitted = when
        self._log(i, when, "obligation_filed", key)
        return i.obligations[key]

    def obligation_deadline(self, i: Incident, key: str) -> datetime:
        ob = self.obligation_defs[key]
        state = i.obligations[key]
        if ob.after and ob.after in i.obligations:
            prior = i.obligations[ob.after]
            base = prior.submitted or self.obligation_deadline(i, ob.after)
            return base + timedelta(hours=ob.hours)
        return state.aware + timedelta(hours=ob.hours)

    def obligations_due(self, now: datetime, include_filed: bool = False) -> list[Due]:
        out: list[Due] = []
        for i in self.incidents.values():
            for key, state in i.obligations.items():
                d = self.obligation_deadline(i, key)
                if state.submitted is not None:
                    status = "filed late" if state.submitted > d else "filed"
                    if not include_filed:
                        continue
                else:
                    status = "overdue" if now > d else "open"
                out.append(Due(i, self.obligation_defs[key], d, state.submitted, status))
        return sorted(out, key=lambda x: (x.status != "overdue", x.deadline))

    # ----------------------------------------------------------------------------------------------------- measures
    def mttr_hours(self) -> float | None:
        done = [i for i in self.incidents.values() if i.resolved]
        if not done:
            return None
        return sum((i.resolved - i.opened).total_seconds() for i in done if i.resolved) / len(done) / 3600

    def metrics(self, now: datetime, since: datetime | None = None, until: datetime | None = None) -> Any:
        from .stats import compute
        return compute(self, now, since, until)

    def postmortem(self, id: str) -> str:
        from .report import postmortem
        return postmortem(self, id)

    def gaps(self, id: str) -> list[str]:
        from .report import gaps
        return gaps(self, id)

    def report(self, now: datetime, days: int = 7) -> str:
        from .report import management_report
        return management_report(self, now, days)

    # -------------------------------------------------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        from .store import register_to_dict
        return register_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Register:
        from .store import register_from_dict
        return register_from_dict(data)

    def save(self, path: str) -> None:
        """Write the register as JSON, atomically, so a crash never leaves half a file."""
        directory = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".incidents-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @classmethod
    def load(cls, path: str) -> Register:
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))
