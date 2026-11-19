"""Risk scoring and severity bands."""
from __future__ import annotations

from dataclasses import dataclass


def risk_score(impact: int, likelihood: int, detectability: int) -> int:
    """Each factor is 1 to 5. High detectability lowers risk: 5 means it is caught fast."""
    for name, value in (("impact", impact), ("likelihood", likelihood), ("detectability", detectability)):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
            raise ValueError(f"{name} must be a whole number from 1 to 5")
    return impact * likelihood * (6 - detectability)


@dataclass(frozen=True)
class Bands:
    """Score thresholds for each severity. The score runs from 1 to 125."""

    sev1: int = 60
    sev2: int = 30
    sev3: int = 12

    def __post_init__(self) -> None:
        if not 1 <= self.sev3 <= self.sev2 <= self.sev1 <= 125:
            raise ValueError("thresholds must satisfy 1 <= sev3 <= sev2 <= sev1 <= 125")

    def severity(self, score: int) -> str:
        return "SEV1" if score >= self.sev1 else "SEV2" if score >= self.sev2 else "SEV3" if score >= self.sev3 else "SEV4"


DEFAULT_BANDS = Bands()


def severity(score: int) -> str:
    return DEFAULT_BANDS.severity(score)
