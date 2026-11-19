"""Regulatory reporting clocks. They run from awareness, which is a legal judgment this library cannot make for you."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Obligation:
    key: str
    label: str
    hours: float
    source: str
    after: str | None = None  # the deadline runs from when this earlier obligation was filed (or was due)


OBLIGATIONS: dict[str, Obligation] = {o.key: o for o in (
    Obligation("gdpr_33", "GDPR personal data breach: notify the supervisory authority", 72, "GDPR Art. 33(1)"),
    Obligation("ai_act_73_general", "EU AI Act serious incident: general deadline", 15 * 24, "EU AI Act Art. 73(2)"),
    Obligation("ai_act_73_widespread", "EU AI Act serious incident: widespread infringement or critical infrastructure", 48, "EU AI Act Art. 73(3)"),
    Obligation("ai_act_73_death", "EU AI Act serious incident: death of a person", 10 * 24, "EU AI Act Art. 73(4)"),
    Obligation("nis2_early_warning", "NIS2 significant incident: early warning", 24, "NIS2 Art. 23(4)(a)"),
    Obligation("nis2_notification", "NIS2 significant incident: incident notification", 72, "NIS2 Art. 23(4)(b)"),
    Obligation("nis2_final", "NIS2 significant incident: final report (one month, taken as 30 days)", 30 * 24, "NIS2 Art. 23(4)(d)", after="nis2_notification"),
)}
