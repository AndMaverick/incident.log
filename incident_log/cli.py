"""``python -m incident_log``: run the register from a terminal or a pipeline. State lives in one JSON file."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from .model import ACTION_KINDS
from .register import Register


def _when(text: str | None) -> datetime:
    """An ISO 8601 time, or now in UTC. Times without an offset are taken as UTC so the file never mixes naive and aware."""
    if not text:
        return datetime.now(timezone.utc)
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _load(path: str) -> Register:
    return Register.load(path) if os.path.exists(path) else Register()


def _fmt(d: datetime | None) -> str:
    return "-" if d is None else f"{d:%Y-%m-%d %H:%M}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="incident_log", description="An incident register for AI systems.")
    ap.add_argument("--db", default=os.environ.get("INCIDENT_LOG_DB", "incidents.json"), help="register file (default incidents.json)")
    ap.add_argument("--at", help="ISO 8601 time to use instead of now (also used for backfilling and tests)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open")
    o.add_argument("id")
    o.add_argument("title")
    o.add_argument("--impact", type=int, required=True)
    o.add_argument("--likelihood", type=int, required=True)
    o.add_argument("--detectability", type=int, required=True)
    o.add_argument("--category", default="other")
    o.add_argument("--system", default="")
    o.add_argument("--description", default="")
    o.add_argument("--impact-text", default="", help="what happened to whom, in plain words")
    o.add_argument("--occurred", help="when it actually began")
    o.add_argument("--detected-by", default="unknown")
    o.add_argument("--owner", default="")
    o.add_argument("--customers", type=int, default=0)
    o.add_argument("--personal-data", action="store_true")
    for name in ("ack", "mitigate", "reopen", "pause", "resume"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--by", default="")
        p.add_argument("--note", default="")
    r = sub.add_parser("resolve")
    r.add_argument("id")
    r.add_argument("--cause", default="")
    r.add_argument("--fix", default="")
    n = sub.add_parser("note")
    n.add_argument("id")
    n.add_argument("text")
    rc = sub.add_parser("reclassify")
    rc.add_argument("id")
    rc.add_argument("severity")
    rc.add_argument("--reason", default="")
    a = sub.add_parser("action", help="add a follow-up")
    a.add_argument("id")
    a.add_argument("text")
    a.add_argument("--owner", default="")
    a.add_argument("--due")
    a.add_argument("--kind", choices=ACTION_KINDS, default="other")
    a.add_argument("--ref", default="")
    d = sub.add_parser("done", help="complete a follow-up")
    d.add_argument("id")
    d.add_argument("action")
    t = sub.add_parser("track", help="start a regulatory clock")
    t.add_argument("id")
    t.add_argument("key")
    t.add_argument("--aware", help="when you became aware (default: when the incident was opened)")
    s = sub.add_parser("submit", help="record that a report was filed")
    s.add_argument("id")
    s.add_argument("key")
    st = sub.add_parser("status", help="what is open, late, due, and who should be told; exit 1 if anything is late")
    st.add_argument("--no-fail", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    pm = sub.add_parser("postmortem")
    pm.add_argument("id")
    g = sub.add_parser("gaps", help="what a postmortem is still missing; exit 1 if anything")
    g.add_argument("id")
    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int, default=7)
    mt = sub.add_parser("metrics")
    mt.add_argument("--json", action="store_true")
    sub.add_parser("obligations", help="list the built-in reporting duties")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "obligations":
            for ob in Register().obligation_defs.values():
                print(f"{ob.key:<24}{ob.hours:>6g} h  {ob.source}  {ob.label}")
            return 0
        now = _when(args.at)
        reg = _load(args.db)
        changed = True
        code = 0
        if args.cmd == "open":
            i = reg.open(args.id, args.title, args.impact, args.likelihood, args.detectability, now, category=args.category,
                         system=args.system, description=args.description, occurred=_when(args.occurred) if args.occurred else None,
                         detected_by=args.detected_by, owner=args.owner, customers_affected=args.customers, personal_data=args.personal_data)
            i.impact = args.impact_text
            print(f"{i.id} opened as {i.severity} (risk score {i.score}); resolve by {_fmt(reg.policy.deadline(i, 'resolve'))}")
        elif args.cmd == "ack":
            reg.acknowledge(args.id, now, args.by)
        elif args.cmd == "mitigate":
            reg.mitigate(args.id, now, args.note, args.by)
        elif args.cmd == "resolve":
            reg.resolve(args.id, now, args.cause, args.fix)
        elif args.cmd == "reopen":
            reg.reopen(args.id, now, args.note)
        elif args.cmd == "pause":
            reg.pause(args.id, now, args.note)
        elif args.cmd == "resume":
            reg.resume(args.id, now)
        elif args.cmd == "note":
            reg.note(args.id, now, args.text)
        elif args.cmd == "reclassify":
            reg.reclassify(args.id, args.severity, now, args.reason)
        elif args.cmd == "action":
            act = reg.add_action(args.id, args.text, args.owner, _when(args.due) if args.due else None, args.kind, args.ref)
            print(f"{args.id} {act.id}: {act.text}")
        elif args.cmd == "done":
            reg.complete_action(args.id, args.action, now)
        elif args.cmd == "track":
            reg.track(args.id, args.key, _when(args.aware) if args.aware else None)
            print(f"{args.key} due {_fmt(reg.obligation_deadline(reg.get(args.id), args.key))}")
        elif args.cmd == "submit":
            reg.submit(args.id, args.key, now)
        else:
            changed = False
            if args.cmd == "status":
                open_items = [i for i in reg.incidents.values() if i.resolved is None]
                print(f"{len(open_items)} open")
                for i in sorted(open_items, key=lambda i: (i.severity, i.opened)):
                    print(f"  {i.id:<10}{i.severity}  opened {_fmt(i.opened)}  resolve by {_fmt(reg.policy.deadline(i, 'resolve'))}  {i.title}")
                breaches = reg.breaches(now)
                for b in breaches:
                    print(f"LATE  {b.incident.id} {b.stage}: {b.overdue.total_seconds() / 3600:.1f} h past {_fmt(b.deadline)}")
                for e in reg.escalations(now):
                    print(f"TELL  {e.incident.id}: {e.role} (due {_fmt(e.due)})")
                overdue = [x for x in reg.obligations_due(now) if x.status == "overdue"]
                for x in reg.obligations_due(now):
                    print(f"DUTY  {x.incident.id}: {x.obligation.label}, {x.status}, due {_fmt(x.deadline)}")
                code = 1 if (breaches or overdue) and not args.no_fail else 0
            elif args.cmd == "list":
                for i in reg.incidents.values():
                    if args.all or i.resolved is None:
                        print(f"{i.id:<10}{i.severity}  {'open' if i.resolved is None else 'resolved':<9}{_fmt(i.opened)}  {i.category:<16}{i.title}")
            elif args.cmd == "postmortem":
                print(reg.postmortem(args.id))
            elif args.cmd == "gaps":
                found = reg.gaps(args.id)
                print("\n".join(f"- {g}" for g in found) if found else "no gaps")
                code = 1 if found else 0
            elif args.cmd == "report":
                print(reg.report(now, args.days))
            elif args.cmd == "metrics":
                m = reg.metrics(now)
                if args.json:
                    print(json.dumps(m, default=lambda o: o.__dict__, indent=1))
                else:
                    for label, s in (("detect", m.mttd), ("acknowledge", m.mtta), ("mitigate", m.mttm), ("resolve", m.mttr)):
                        print(f"time to {label:<12}" + (f"median {s.median:.2f} h  p90 {s.p90:.2f} h  (n={s.n})" if s else "no data"))
                    for stage in ("acknowledge", "mitigate", "resolve"):
                        att = m.attainment(stage)
                        print(f"on time {stage:<12}" + (f"{att:.0%}  ({m.sla[stage][0]} of {m.sla[stage][1]})" if att is not None else "no data"))
        if changed:
            reg.save(args.db)
        return code
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc.args[0] if isinstance(exc, KeyError) and exc.args else exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
