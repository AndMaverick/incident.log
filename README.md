# incident.log

An incident register for AI systems. When one fails, someone has to answer for it, and the answers regulators, customers and your own executives ask for are specific: how long until a person looked, how long until it stopped, whether you hit your own targets, whether a report was due and filed, and whether it will happen again. incident.log keeps those answers as a by-product of running the incident, and its postmortems say what they are still missing. Standard library only.

```
pip install git+https://github.com/AndMaverick/incident.log
```

## What it does

```python
from datetime import datetime
from incident_log import Register

reg = Register()
reg.open("INC-101", "Assistant quoted a refund policy that does not exist",
         impact=5, likelihood=4, detectability=2, when=datetime(2026, 3, 2, 8, 0),
         category="hallucination", system="support-assistant", detected_by="customer",
         occurred=datetime(2026, 3, 2, 6, 10), customers_affected=14)        # SEV1, risk score 80
reg.acknowledge("INC-101", datetime(2026, 3, 2, 8, 12), by="maria")
reg.mitigate("INC-101", datetime(2026, 3, 2, 8, 55), "Retrieval pinned to the current policy")
reg.track("INC-101", "ai_act_73_general")                                    # start a regulatory clock
now = datetime(2026, 3, 4, 12, 0)
reg.breaches(now)         # every missed target (acknowledge, mitigate, resolve), most overdue first
reg.escalations(now)      # who should have been told by now and has not been
reg.obligations_due(now)  # reporting duties, overdue first
print(reg.postmortem("INC-101"))
```

- **Three targets, not one.** Acknowledge, mitigate and resolve each have a target per severity (defaults: SEV1 15 minutes, 1 hour, 4 hours). Set your own with `Policy`, which rejects targets that run backwards. The original `breached()` still works.
- **A clock that can pause.** Waiting on a customer or on legal should not count against you. `pause` and `resume` stop the clock, deadlines move by exactly the paused time, and an incident that is paused is never reported late.
- **Escalation that follows the clock.** A ladder per severity (on-call, then engineering lead at 25% of the resolve target, then an executive sponsor at 50%). `escalations(now)` returns who is owed a call and has not had one. It stops once the incident is mitigated.
- **Regulatory clocks.** Built in with their sources: GDPR Art. 33 (72 hours), EU AI Act Art. 73 serious incidents (15 days, 2 days for widespread infringement, 10 days for death), NIS2 Art. 23 (24 hours early warning, 72 hours notification, final report one month after the notification). Add your own contract or sector duties with `define_obligation`.
- **Detection and response, measured.** Time to detect (when it began to when you knew), acknowledge, mitigate and resolve, each as mean, median and p90, plus attainment per target. The share of incidents found by users or third parties before your own monitoring is the number that tells you whether detection works.
- **The failure that came back.** `repeats` finds incidents on the same system with the same failure mode inside a window, the ones the last fix did not hold. `calibration` checks the scoring itself: for each predicted severity, how long incidents really took and how often a person later moved the severity.
- **Postmortems that audit themselves.** A timeline, a response-against-targets table, regulatory duties and follow-ups with owners and due dates. `gaps()` lists what a reviewer would send it back for: no root cause, no impact, no acknowledgement time, no follow-up to detect it sooner, and for AI output failures (hallucination, injection, leakage, bias) no regression case added to the eval suite. Pairs with [eval.forge](https://github.com/AndMaverick/eval.forge): the follow-up records the case id.
- **A register you can keep.** One JSON file, written atomically, every field and every event kept. A CLI runs the whole thing, and `status` exits 1 when a target is missed or a duty is overdue, so a scheduled job can page someone.

## Command line

A bad morning for a support assistant. `examples/demo.sh` reproduces this output exactly, because every time is passed with `--at`:

```
INC-101 opened as SEV1 (risk score 80); resolve by 2026-03-02 12:00
INC-102 opened as SEV2 (risk score 48); resolve by 2026-03-03 11:30
gdpr_33 due 2026-03-05 11:30

--- two days later: INC-102 was never picked up ---
1 open
  INC-102   SEV2  opened 2026-03-02 11:30  resolve by 2026-03-03 11:30  Support transcripts logged with card numbers
LATE  INC-102 acknowledge: 47.5 h past 2026-03-02 12:30
LATE  INC-102 mitigate: 40.5 h past 2026-03-02 19:30
LATE  INC-102 resolve: 24.5 h past 2026-03-03 11:30
TELL  INC-102: on-call (due 2026-03-02 11:30)
TELL  INC-102: engineering lead (due 2026-03-02 23:30)
TELL  INC-102: executive sponsor (due 2026-03-03 09:06)
DUTY  INC-102: GDPR personal data breach: notify the supervisory authority, open, due 2026-03-05 11:30

--- what INC-101's postmortem still lacks ---
- no summary of what happened
- no follow-up to detect this failure sooner
- no regression case added to the eval suite
```

```
python -m incident_log open|ack|mitigate|resolve|reopen|reclassify|pause|resume|note|action|done|track|submit ...
python -m incident_log status | list | postmortem ID | gaps ID | report --days 7 | metrics [--json] | obligations
```

The register lives in `incidents.json` (or `--db`, or `INCIDENT_LOG_DB`). Times without an offset are read as UTC. Exit codes: `0` fine, `1` something is late, overdue or missing, `2` error.

## Honest limits

- **Regulatory clocks start at awareness, and what counts as awareness is a legal judgment.** This tracks the clock you tell it to start. It does not decide whether an incident is reportable, which authority gets it, or what a report must contain. The built-in durations come from the texts of the cited articles, and national rules (NIS2 especially) differ in detail. Confirm with counsel before you rely on one.
- **The risk score is a prioritisation heuristic, not a measurement.** Impact times likelihood times how hard it is to detect gives a number that is easy to argue with. `calibration` shows whether it is earning its keep.
- **The default targets are a starting point.** They are not a standard. Hold yourself to numbers your team and your customers agreed.
- **Time to detect needs the start time.** It is only reported for incidents where you recorded when the problem began, and that is often a reconstruction.
- **It records, it does not page.** It will tell you who should have been called. Calling them is your on-call tool's job.

## Tests

```
python -m unittest discover -s tests -t . -v
```

67 tests, with durations and attainment worked out by hand in the test cases. Ruff and mypy strict run in CI on Python 3.10 to 3.13.

MIT licensed. Built by [AndMaverick LLC](https://www.andmaverick.com).

---

**Related reading:** [Nobody Signs for the Agent](https://blog.andmaverick.com/nobody-signs-for-the-agent?utm_source=github&utm_medium=repo&utm_campaign=incident.log)

**If this is your problem.** If a system you run can fail in ways that matter, the controls belong in the architecture, not in the postmortem. I am happy to talk through yours. [Begin a conversation](https://calendly.com/andmaverick?utm_source=github&utm_medium=repo&utm_campaign=incident.log).
