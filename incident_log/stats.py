"""Measures over a register: how fast you notice, respond and fix, whether you hit your targets, and what keeps coming back."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .model import SEVERITIES, Incident

if TYPE_CHECKING:
    from .register import Register

EXTERNAL = ("user", "customer", "third_party")


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q from 0 to 100."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float
    median: float
    p90: float

    @classmethod
    def of(cls, values: Sequence[float]) -> Summary | None:
        if not values:
            return None
        return cls(len(values), sum(values) / len(values), percentile(values, 50), percentile(values, 90))


@dataclass
class Metrics:
    incidents: int
    open: int
    by_severity: dict[str, int]
    by_category: dict[str, int]
    mttd: Summary | None  # hours from when it began to when it was recorded: only incidents with a known start
    mtta: Summary | None
    mttm: Summary | None
    mttr: Summary | None
    sla: dict[str, tuple[int, int]]  # stage -> (met, due so far)
    reopen_rate: float
    detected_by: dict[str, int]
    external_detection_share: float | None  # of incidents with a known detector, the share users or third parties found first
    actions_done: int
    actions_total: int
    actions_overdue: int
    repeats: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (system, category, incident ids)

    def attainment(self, stage: str) -> float | None:
        met, total = self.sla[stage]
        return met / total if total else None


def repeats(incidents: Sequence[Incident], window_days: float = 30) -> list[tuple[str, str, list[str]]]:
    """Incidents on the same system with the same failure mode within ``window_days`` of each other: the ones the last fix did not hold."""
    groups: dict[tuple[str, str], list[Incident]] = {}
    for i in incidents:
        if i.system:
            groups.setdefault((i.system, i.category), []).append(i)
    out = []
    gap = timedelta(days=window_days)
    for (system, category), items in sorted(groups.items()):
        items.sort(key=lambda i: i.opened)
        cluster = [items[0]]
        for i in items[1:]:
            if i.opened - cluster[-1].opened <= gap:
                cluster.append(i)
            else:
                if len(cluster) > 1:
                    out.append((system, category, [c.id for c in cluster]))
                cluster = [i]
        if len(cluster) > 1:
            out.append((system, category, [c.id for c in cluster]))
    return out


def hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def compute(reg: Register, now: datetime, since: datetime | None = None, until: datetime | None = None) -> Metrics:
    items = [i for i in reg.incidents.values() if (since is None or i.opened >= since) and (until is None or i.opened < until)]
    mttd = [hours(i.occurred, i.opened) for i in items if i.occurred]
    mtta = [hours(i.opened, i.acknowledged) for i in items if i.acknowledged]
    mttm = [hours(i.opened, m) for i in items if (m := i.mitigated or i.resolved)]  # resolving implies mitigating
    mttr = [hours(i.opened, i.resolved) for i in items if i.resolved]
    sla: dict[str, tuple[int, int]] = {}
    for stage in ("acknowledge", "mitigate", "resolve"):
        met = total = 0
        for i in items:
            done = {"acknowledge": i.acknowledged, "mitigate": i.mitigated or i.resolved, "resolve": i.resolved}[stage]
            deadline = reg.policy.deadline(i, stage)
            if deadline is None:
                continue
            if done is not None:
                total += 1
                met += done <= deadline
            elif now > deadline:
                total += 1
        sla[stage] = (met, total)
    detected: dict[str, int] = {}
    for i in items:
        detected[i.detected_by] = detected.get(i.detected_by, 0) + 1
    known = sum(n for k, n in detected.items() if k != "unknown")
    actions = [a for i in items for a in i.actions]
    resolved = [i for i in items if i.resolved or i.reopened]
    return Metrics(
        len(items), sum(i.resolved is None for i in items),
        {s: sum(i.severity == s for i in items) for s in SEVERITIES},
        dict(sorted(((c, n) for c in {i.category for i in items} if (n := sum(i.category == c for i in items))), key=lambda kv: -kv[1])),
        Summary.of(mttd), Summary.of(mtta), Summary.of(mttm), Summary.of(mttr), sla,
        sum(i.reopened > 0 for i in resolved) / len(resolved) if resolved else 0.0,
        detected, (sum(detected.get(k, 0) for k in EXTERNAL) / known) if known else None,
        sum(a.done is not None for a in actions), len(actions), sum(a.overdue(now) for a in actions), repeats(items))


def calibration(reg: Register) -> dict[str, dict[str, float | int | None]]:
    """Is the scoring honest? For each severity the risk score predicted: how long incidents really took, how often customers
    were affected, and how often a person later moved the severity up or down."""
    out: dict[str, dict[str, float | int | None]] = {}
    for sev in SEVERITIES:
        items = [i for i in reg.incidents.values() if i.initial_severity == sev]
        done = [(i.resolved - i.opened).total_seconds() / 3600 for i in items if i.resolved]
        out[sev] = {
            "n": len(items), "mean_hours_to_resolve": sum(done) / len(done) if done else None,
            "share_with_customers_affected": sum(i.customers_affected > 0 for i in items) / len(items) if items else None,
            "raised": sum(SEVERITIES.index(i.severity) < SEVERITIES.index(sev) for i in items),
            "lowered": sum(SEVERITIES.index(i.severity) > SEVERITIES.index(sev) for i in items),
        }
    return out
