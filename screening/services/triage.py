"""
Triage level and its justification.

Triage is derived from the model's score and the thresholds in force, using
simple arithmetic. It is not a second model, and it is not a clinical severity
rating: it is a priority label that says how strongly the screening result
suggests this case needs attention first.

The justification is written out so the result page can show why a case was put
in a band, rather than asserting the band on its own.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TriageDecision:
    level: str  # LOW, MEDIUM or HIGH
    justification: str


class TriageJustifier:
    """Turns a score and its thresholds into a triage level with a reason."""

    def decide(self, probability, low_medium, medium_high):
        score = Decimal(str(probability))
        low_medium = Decimal(str(low_medium))
        medium_high = Decimal(str(medium_high))

        if score >= medium_high:
            return TriageDecision(
                level="HIGH",
                justification=(
                    f"A score of {score:.4f} is at or above the high-suspicion "
                    f"threshold of {medium_high:.3f}. Cases in this band are "
                    "prioritised for clinical review and confirmatory testing."
                ),
            )

        if score >= low_medium:
            return TriageDecision(
                level="MEDIUM",
                justification=(
                    f"A score of {score:.4f} falls between the thresholds of "
                    f"{low_medium:.3f} and {medium_high:.3f}. The result suggests "
                    "TB is possible and warrants clinical review."
                ),
            )

        return TriageDecision(
            level="LOW",
            justification=(
                f"A score of {score:.4f} is below the low-suspicion threshold of "
                f"{low_medium:.3f}. Routine clinical judgement applies; this "
                "result does not raise TB as a priority."
            ),
        )
