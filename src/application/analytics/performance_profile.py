"""Optional aggregate profiling for a single historical analytics invocation.

Wall-clock values are exclusive between named stages. Query execute includes
driver/network/possible row buffering, not server-only PostgreSQL execution.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class ProcessingProfile:
    sql_execute_seconds: float = 0.0
    row_materialization_seconds: float = 0.0
    assignment_seconds: float = 0.0
    continuity_seconds: float = 0.0
    observed_time_seconds: float = 0.0
    attribution_seconds: float = 0.0
    bucketing_seconds: float = 0.0
    spatial_assessment_seconds: float = 0.0
    qualification_seconds: float = 0.0
    grid_seconds: float = 0.0
    aggregation_seconds: float = 0.0
    other_seconds: float = 0.0
    total_seconds: float = 0.0
    sql_query_count: int = 0
    location_page_count: int = 0
    neighbor_query_count: int = 0
    rows_fetched: int = 0
    locations_processed: int = 0
    fragments_created: int = 0
    result_count: int = 0
    cell_count: int = 0

    def add(self, stage: str, seconds: float) -> None:
        setattr(self, stage, getattr(self, stage) + seconds)

    def reset(self) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, 0 if name.endswith("count") or name in (
                "rows_fetched", "locations_processed", "fragments_created",
            ) else 0.0)

    def finish(self, total_seconds: float) -> None:
        self.total_seconds = total_seconds
        accounted = sum(getattr(self, name) for name in (
            "sql_execute_seconds", "row_materialization_seconds",
            "assignment_seconds", "continuity_seconds", "observed_time_seconds",
            "attribution_seconds", "bucketing_seconds",
            "spatial_assessment_seconds", "qualification_seconds",
            "grid_seconds", "aggregation_seconds",
        ))
        self.other_seconds = max(0.0, total_seconds - accounted)

    def as_dict(self) -> dict[str, float | int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}
