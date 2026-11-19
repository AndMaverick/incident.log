"""Documents: the postmortem, the gaps in it, and the management report."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .model import OUTPUT_FAILURES

if TYPE_CHECKING:
    from .register import Register


def _t(value: datetime | None) -> str:
    if value is None:
        return "-"
    return f"{value:%Y-%m-%d %H:%M}" + (f" {value:%Z}" if value.tzinfo else "")


def _h(hours: float | None) -> str:
    if hours is None:
        return "-"
    return f"{hours * 60:.0f} min" if hours < 1 else f"{hours:.1f} h"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def gaps(reg: Register, id: str) -> list[str]:
    """What a reviewer would send the postmortem back for. An empty list means it is complete enough to close."""
    i = reg.get(id)
    out: list[str] = []
    if i.resolved is None:
        out.append("incident is still open")
    if i.resolved is not None:
        if not i.cause.strip():
            out.append("no root cause recorded")
        if not i.fix.strip():
            out.append("no fix recorded")
    if not i.description.strip():
        out.append("no summary of what happened")
    if not i.impact.strip():
        out.append("impact is not described")
    if i.acknowledged is None:
        out.append("no acknowledgement time recorded, so response time cannot be measured")
    if i.detected_by == "unknown":
        out.append("how it was detected is not recorded")
    if i.occurred is None:
        out.append("start time unknown, so time to detect cannot be measured")
    kinds = {a.kind for a in i.actions}
    if "detection" not in kinds:
        out.append("no follow-up to detect this failure sooner")
    if i.category in OUTPUT_FAILURES and "regression_case" not in kinds:
        out.append("no regression case added to the eval suite")
    for a in i.actions:
        if not a.owner:
            out.append(f"action {a.id} has no owner")
        if a.due is None:
            out.append(f"action {a.id} has no due date")
    for key, state in i.obligations.items():
        if state.submitted is None:
            out.append(f"reporting duty {key} has not been filed")
    return out


def postmortem(reg: Register, id: str) -> str:
    i = reg.get(id)
    p = reg.policy
    status = f"resolved {i.resolved:%Y-%m-%d %H:%M}" if i.resolved else "open"
    sev = f"{i.severity} (risk score {i.score}" + (f", opened as {i.initial_severity}" if i.severity != i.initial_severity else "") + ")"
    lines = [f"# Postmortem: {i.title}", "", f"- ID: {i.id}", f"- Severity: {sev}", f"- Opened: {i.opened:%Y-%m-%d %H:%M}", f"- Status: {status}"]
    if i.category != "other" or i.system:
        lines.append(f"- Failure mode: {i.category}" + (f", system: {i.system}" if i.system else ""))
    if i.owner:
        lines.append(f"- Owner: {i.owner}")
    lines += ["", "## Summary", i.description or "_to be completed_", "", "## Impact"]
    lines.append(i.impact or "_to be completed_")
    if i.customers_affected:
        lines.append(f"\nCustomers affected: {i.customers_affected}.")
    if i.personal_data:
        lines.append("\nPersonal data was involved.")
    lines += ["", "## Detection"]
    detect = f"Detected by: {i.detected_by}."
    if i.occurred:
        detect += f" The problem began {_t(i.occurred)} and was recorded {_h(i.hours_to(i.opened, i.occurred))} later."
    lines.append(detect)
    lines += ["", "## Timeline", "", "| Time | Event | Detail |", "|---|---|---|"]
    for e in sorted(i.events, key=lambda e: e.at):
        lines.append(f"| {_t(e.at)} | {e.kind} | {_cell((e.text + (' (' + e.actor + ')' if e.actor else '')).strip())} |")
    lines += ["", "## Response against targets", "", "| Stage | Target | Actual | Met |", "|---|---|---|---|"]
    for stage, done in (("acknowledge", i.acknowledged), ("mitigate", i.mitigated or i.resolved), ("resolve", i.resolved)):
        target = {"acknowledge": p.acknowledge_hours, "mitigate": p.mitigate_hours, "resolve": p.resolve_hours}[stage][i.severity]
        d = p.deadline(i, stage)
        met = "-" if done is None or d is None else "yes" if done <= d else "no"
        lines.append(f"| {stage} | {_h(target)} | {_h(i.hours_to(done))} | {met} |")
    lines += ["", "## Cause", i.cause or "_to be completed_", "", "## Fix", i.fix or "_to be completed_"]
    if i.obligations:
        lines += ["", "## Reporting duties", "", "| Duty | Due | Filed |", "|---|---|---|"]
        for key in i.obligations:
            lines.append(f"| {_cell(reg.obligation_defs[key].label)} ({reg.obligation_defs[key].source}) | {_t(reg.obligation_deadline(i, key))} | {_t(i.obligations[key].submitted)} |")
    lines += ["", "## Follow-ups"]
    for a in i.actions:
        meta = ", ".join(x for x in (a.owner, f"due {a.due:%Y-%m-%d}" if a.due else "", a.kind if a.kind != "other" else "", a.ref) if x)
        lines.append(f"- [{'x' if a.done else ' '}] {a.text}" + (f" ({meta})" if meta else ""))
    kinds = {a.kind for a in i.actions}
    if "detection" not in kinds:
        lines.append("- [ ] Add a detection for this failure mode")
    if "regression_case" not in kinds:
        lines.append("- [ ] Add a regression case to the eval suite")
    open_gaps = gaps(reg, id)
    if open_gaps:
        lines += ["", "## Open gaps", *[f"- {g}" for g in open_gaps]]
    return "\n".join(lines)


def management_report(reg: Register, now: datetime, days: int = 7) -> str:
    since = now - timedelta(days=days)
    m = reg.metrics(now, since, now + timedelta(seconds=1))
    lines = [f"# Incident report: {since:%Y-%m-%d} to {now:%Y-%m-%d}", ""]
    sev = ", ".join(f"{n} {s}" for s, n in m.by_severity.items() if n) or "none"
    lines.append(f"{m.incidents} incidents opened ({sev}); {m.open} still open.")
    for label, s in (("Time to acknowledge", m.mtta), ("Time to mitigate", m.mttm), ("Time to resolve", m.mttr), ("Time to detect", m.mttd)):
        if s:
            lines.append(f"- {label}: median {_h(s.median)}, p90 {_h(s.p90)} (n={s.n})")
    lines += ["", "## Targets", ""]
    for stage in ("acknowledge", "mitigate", "resolve"):
        met, total = m.sla[stage]
        lines.append(f"- {stage}: {met} of {total} on time" + (f" ({met / total:.0%})" if total else ""))
    breaches = reg.breaches(now)
    if breaches:
        lines += ["", "## Late now", ""]
        for b in breaches[:10]:
            lines.append(f"- {b.incident.id} {b.incident.severity} {b.stage}: {_h(b.overdue.total_seconds() / 3600)} overdue, {b.incident.title}")
    due = reg.obligations_due(now)
    if due:
        lines += ["", "## Reporting duties", ""]
        for d in due[:10]:
            lines.append(f"- {d.incident.id}: {d.obligation.label}, {d.status}, due {_t(d.deadline)}")
    if m.external_detection_share is not None:
        lines += ["", f"Of incidents with a known detector, {m.external_detection_share:.0%} were found by users or third parties before your own monitoring."]
    if m.repeats:
        lines += ["", "## Came back", ""]
        for system, category, ids in m.repeats:
            lines.append(f"- {system} / {category}: {', '.join(ids)}")
    if m.actions_total:
        lines += ["", f"Follow-ups: {m.actions_done} of {m.actions_total} done, {m.actions_overdue} overdue."]
    return "\n".join(lines)
