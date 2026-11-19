"""incident.log: an incident register for AI systems.

Score the risk, hold the response to targets (acknowledge, mitigate, resolve) with a clock that can pause, escalate when an
incident ages, track the reporting duties regulators attach (GDPR, EU AI Act, NIS2 and your own), measure detection and
response, find the failures that keep coming back, and generate postmortems that say what is still missing.
"""
from __future__ import annotations

from .model import (
    ACTION_KINDS,
    CATEGORIES,
    DETECTED_BY,
    OUTPUT_FAILURES,
    SEVERITIES,
    SLA_HOURS,
    Action,
    Event,
    Incident,
    ObligationState,
    deadline_after,
)
from .obligations import OBLIGATIONS, Obligation
from .policy import Breach, Escalation, Policy
from .register import Due, Register
from .report import gaps, management_report, postmortem
from .scoring import DEFAULT_BANDS, Bands, risk_score, severity
from .stats import Metrics, Summary, calibration, percentile, repeats

__version__ = "0.2.0"

__all__ = [
    "Register", "Incident", "Event", "Action", "ObligationState", "Policy", "Bands", "Breach", "Escalation", "Due", "Obligation",
    "OBLIGATIONS", "SLA_HOURS", "SEVERITIES", "CATEGORIES", "DETECTED_BY", "OUTPUT_FAILURES", "ACTION_KINDS", "DEFAULT_BANDS",
    "risk_score", "severity", "deadline_after", "postmortem", "gaps", "management_report", "Metrics", "Summary", "calibration",
    "percentile", "repeats", "__version__",
]
