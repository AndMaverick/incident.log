# incident.log

When an AI system fails, someone has to answer for it. incident.log is the register that makes that routine: score the risk, assign a severity, hold the clock against an SLA, and generate the postmortem. Standard library only.

## Use

```python
from datetime import datetime
from incident_log import Register

register = Register()
register.open("INC-1", "Hallucinated refund policy",
              impact=5, likelihood=4, detectability=2, when=datetime(2026, 3, 1, 9, 0))   # SEV1

register.breached(datetime(2026, 3, 1, 14, 0))    # unresolved and past SLA, most severe first
register.resolve("INC-1", datetime(2026, 3, 1, 11, 0), cause="Stale policy doc", fix="Retrieval filter")
register.mttr_hours()                              # mean time to resolve
print(register.postmortem("INC-1"))                # a structured postmortem, ready to complete
```

## Design

- **Detectability counts.** Risk is impact times likelihood times how hard the failure is to catch. A failure you would notice in a minute scores lower than one that rots silently.
- **Severity sets the clock.** SEV1 is four hours, SEV2 a day, SEV3 three days, SEV4 a week. Breach detection is a single call.
- **Postmortems that end in action.** Every one closes with follow-ups to add a detection and a regression case, so the same failure is caught next time. Pair it with [eval.forge](https://github.com/AndMaverick/eval.forge).

## Tests

```
python -m unittest discover -s tests -t . -v
```

MIT licensed. Built by [AndMaverick LLC](https://www.andmaverick.com).

---

**Related reading:** [Nobody Signs for the Agent](https://blog.andmaverick.com/nobody-signs-for-the-agent?utm_source=github&utm_medium=repo&utm_campaign=incident.log)

**If this is your problem.** If a system you run can fail in ways that matter, the controls belong in the architecture, not in the postmortem. I am happy to talk through yours. [Begin a conversation](https://calendly.com/andmaverick?utm_source=github&utm_medium=repo&utm_campaign=incident.log).
