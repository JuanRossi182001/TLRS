"""Bounded adaptive-continuity window; preserves both sides of local cadence."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter

from src.application.analytics.performance_profile import ProcessingProfile
from src.application.analytics.spatial_assessment import SpatialObservationRef
from src.application.analytics.temporal_continuity import (
    TemporalIntervalAssessment, TemporalContinuityInputError,
    DEFAULT_CADENCE_WINDOW_SIZE, DEFAULT_MIN_CADENCE_SAMPLES,
    DEFAULT_GAP_FACTOR, DEFAULT_MIN_JITTER_ALLOWANCE_SECONDS,
    DEFAULT_MAX_CADENCE_VARIABILITY, _assess_delta_at,
)


@dataclass(slots=True)
class RollingTemporalAnalyzer:
    """Emit each interval once using four preceding and four following deltas.

    This mirrors the default configuration of 1A.3. Change this size if the
    detector's default cadence window changes; tests assert equivalence.
    """

    _buffer: deque[SpatialObservationRef] = field(default_factory=deque)
    _base: int = 0
    _next: int = 0
    _previous: SpatialObservationRef | None = None
    profile: ProcessingProfile | None = None

    def feed(self, observation: SpatialObservationRef) -> tuple[tuple[SpatialObservationRef, SpatialObservationRef, TemporalIntervalAssessment], ...]:
        if not isinstance(observation, SpatialObservationRef):
            raise ValueError("Invalid temporal observation.")
        if not isinstance(observation.observed_at, datetime) or observation.observed_at.tzinfo is not None:
            raise TemporalContinuityInputError("Timestamps must use Manea's UTC-naive datetime convention.")
        if self._previous is not None and (
            observation.observed_at < self._previous.observed_at
            or observation.observed_at == self._previous.observed_at
            and observation.observation_id <= self._previous.observation_id
        ):
            raise ValueError("Observations must be ordered by timestamp and ID.")
        self._previous = observation
        self._buffer.append(observation)
        if len(self._buffer) < 2 * DEFAULT_CADENCE_WINDOW_SIZE + 2:
            return ()
        ready = self._emit_through(self._base + DEFAULT_CADENCE_WINDOW_SIZE)
        self._buffer.popleft()
        self._base += 1
        return ready

    def finish(self) -> tuple[tuple[SpatialObservationRef, SpatialObservationRef, TemporalIntervalAssessment], ...]:
        ready = self._emit_through(self._base + len(self._buffer) - 2)
        self._buffer.clear()
        self._previous = None
        self._base = 0
        self._next = 0
        return ready

    def _emit_through(self, last_index: int) -> tuple[tuple[SpatialObservationRef, SpatialObservationRef, TemporalIntervalAssessment], ...]:
        if last_index < self._next:
            return ()
        started = perf_counter() if self.profile is not None else 0.0
        observations = tuple(self._buffer)
        timestamps = tuple(o.observed_at for o in observations)
        deltas = tuple((end - start).total_seconds() for start, end in zip(timestamps, timestamps[1:]))
        ready = tuple(
            (
                observations[index - self._base],
                observations[index - self._base + 1],
                _assess_delta_at(
                    deltas=deltas, index=index - self._base,
                    start_at=timestamps[index - self._base],
                    end_at=timestamps[index - self._base + 1],
                    cadence_window_size=DEFAULT_CADENCE_WINDOW_SIZE,
                    min_cadence_samples=DEFAULT_MIN_CADENCE_SAMPLES,
                    gap_factor=DEFAULT_GAP_FACTOR,
                    min_jitter_allowance_seconds=DEFAULT_MIN_JITTER_ALLOWANCE_SECONDS,
                    max_cadence_variability=DEFAULT_MAX_CADENCE_VARIABILITY,
                ),
            )
            for index in range(self._next, last_index + 1)
        )
        self._next = last_index + 1
        if self.profile is not None:
            self.profile.continuity_seconds += perf_counter() - started
        return ready
