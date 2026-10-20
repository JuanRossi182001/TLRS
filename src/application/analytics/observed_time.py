from dataclasses import dataclass
from datetime import datetime
from math import isclose
from typing import Sequence

from src.application.analytics.temporal_continuity import (
    ContinuityStatus,
    TemporalIntervalAssessment,
)


class ObservedTimeInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObservedSpan:
    start_at: datetime
    end_at: datetime
    observed_seconds: float


@dataclass(frozen=True, slots=True)
class ObservedTimeMetadata:
    observed_seconds: float
    gap_seconds: float
    indeterminate_seconds: float
    continuous_interval_count: int
    gap_interval_count: int
    indeterminate_interval_count: int
    assessed_seconds: float
    assessment_count: int

    @property
    def unknown_seconds(self) -> float:
        return self.gap_seconds + self.indeterminate_seconds


@dataclass(frozen=True, slots=True)
class ObservedTimeResult:
    spans: tuple[ObservedSpan, ...]
    metadata: ObservedTimeMetadata


def calculate_observed_time(
    assessments: Sequence[TemporalIntervalAssessment],
) -> ObservedTimeResult:
    """Quantify already-classified temporal intervals without reclassifying them."""
    spans: list[ObservedSpan] = []
    observed_seconds = 0.0
    gap_seconds = 0.0
    indeterminate_seconds = 0.0
    continuous_interval_count = 0
    gap_interval_count = 0
    indeterminate_interval_count = 0

    for assessment in assessments:
        _validate_assessment(assessment)
        positive_seconds = max(assessment.delta_seconds, 0.0)

        if assessment.status == ContinuityStatus.CONTINUOUS:
            continuous_interval_count += 1
            observed_seconds += positive_seconds
            if positive_seconds > 0:
                spans.append(
                    ObservedSpan(
                        start_at=assessment.start_at,
                        end_at=assessment.end_at,
                        observed_seconds=positive_seconds,
                    )
                )
        elif assessment.status == ContinuityStatus.GAP:
            gap_interval_count += 1
            gap_seconds += positive_seconds
        elif assessment.status == ContinuityStatus.INDETERMINATE:
            indeterminate_interval_count += 1
            indeterminate_seconds += positive_seconds
        else:
            raise ObservedTimeInputError("Assessment has an unsupported continuity status.")

    metadata = ObservedTimeMetadata(
        observed_seconds=observed_seconds,
        gap_seconds=gap_seconds,
        indeterminate_seconds=indeterminate_seconds,
        continuous_interval_count=continuous_interval_count,
        gap_interval_count=gap_interval_count,
        indeterminate_interval_count=indeterminate_interval_count,
        assessed_seconds=(
            observed_seconds + gap_seconds + indeterminate_seconds
        ),
        assessment_count=len(assessments),
    )
    return ObservedTimeResult(spans=tuple(spans), metadata=metadata)


def _validate_assessment(assessment: TemporalIntervalAssessment) -> None:
    if not isinstance(assessment, TemporalIntervalAssessment):
        raise ObservedTimeInputError("All inputs must be TemporalIntervalAssessment values.")
    if assessment.end_at < assessment.start_at:
        raise ObservedTimeInputError("Assessment end_at must not precede start_at.")
    if assessment.delta_seconds < 0:
        raise ObservedTimeInputError("Assessment delta_seconds must not be negative.")

    duration_seconds = (assessment.end_at - assessment.start_at).total_seconds()
    if not isclose(
        assessment.delta_seconds,
        duration_seconds,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise ObservedTimeInputError(
            "Assessment delta_seconds must match the timestamp interval."
        )
