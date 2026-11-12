"""Known device-to-animal intervals, independent of the current device pointer."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Sequence


class AssignmentHistoryInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AssignmentRef:
    assignment_id: int
    asset_id: int
    device_id: int
    assigned_at: datetime
    unassigned_at: datetime | None


@dataclass(frozen=True, slots=True)
class AssignmentWindow:
    assignment: AssignmentRef
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class AssignmentCoverage:
    windows: tuple[AssignmentWindow, ...]
    eligible_assignment_seconds: float


def resolve_assignment_windows(
    assignments: Sequence[AssignmentRef], *, window_start: datetime, window_end: datetime,
) -> AssignmentCoverage:
    """Reject ambiguous history; calculate known eligible animal-seconds only."""
    for value in (window_start, window_end):
        if not isinstance(value, datetime) or value.tzinfo is not None:
            raise AssignmentHistoryInputError("Window must use UTC-naive datetimes.")
    if window_start >= window_end:
        raise AssignmentHistoryInputError("Window must be positive.")
    ids: set[int] = set()
    last_by_device: dict[int, datetime | None] = {}
    last_by_asset: dict[int, datetime | None] = {}
    windows: list[AssignmentWindow] = []
    total = timedelta()
    ordered: list[AssignmentRef] = []
    for assignment in assignments:
        if not isinstance(assignment, AssignmentRef):
            raise AssignmentHistoryInputError("Invalid assignment record.")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0
            for v in (assignment.assignment_id, assignment.asset_id, assignment.device_id)
        ):
            raise AssignmentHistoryInputError("Assignment IDs must be positive integers.")
        for value in (assignment.assigned_at, assignment.unassigned_at):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is not None):
                raise AssignmentHistoryInputError("Assignments must use UTC-naive datetimes.")
        if assignment.unassigned_at is not None and assignment.unassigned_at < assignment.assigned_at:
            raise AssignmentHistoryInputError("Assignment end precedes its start.")
        if assignment.assignment_id in ids:
            raise AssignmentHistoryInputError("Duplicate assignment ID.")
        ids.add(assignment.assignment_id)
        ordered.append(assignment)
    for assignment in sorted(ordered, key=lambda a: (a.assigned_at, a.assignment_id)):
        for key, previous in ((assignment.device_id, last_by_device), (assignment.asset_id, last_by_asset)):
            if key in previous and (previous[key] is None or previous[key] > assignment.assigned_at):
                raise AssignmentHistoryInputError("Overlapping device or asset assignments.")
        last_by_device[assignment.device_id] = assignment.unassigned_at
        last_by_asset[assignment.asset_id] = assignment.unassigned_at
        start = max(window_start, assignment.assigned_at)
        end = min(window_end, assignment.unassigned_at or window_end)
        if start < end:
            windows.append(AssignmentWindow(assignment, start, end))
            total += end - start
    return AssignmentCoverage(tuple(windows), total.total_seconds())


def temporal_coverage_ratio(observed_seconds: float, eligible_assignment_seconds: float) -> float | None:
    for value in (observed_seconds, eligible_assignment_seconds):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise AssignmentHistoryInputError("Coverage seconds must be finite numbers.")
    if eligible_assignment_seconds < 0 or observed_seconds < 0 or observed_seconds > eligible_assignment_seconds:
        raise AssignmentHistoryInputError("Observed time exceeds known assignment time.")
    return observed_seconds / eligible_assignment_seconds if eligible_assignment_seconds else None
