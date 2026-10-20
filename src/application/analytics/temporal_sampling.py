from dataclasses import dataclass
from math import ceil, isfinite


# Every resolution divides a UTC day, so future bucket boundaries can align to
# stable minute, hour, and day boundaries.
ALLOWED_BUCKET_SECONDS = (
    60,       # 1 min
    120,      # 2 min
    300,      # 5 min
    600,      # 10 min
    900,      # 15 min
    1200,     # 20 min
    1800,     # 30 min
    2700,     # 45 min
    3600,     # 1 h
    5400,     # 1 h 30
    7200,     # 2 h
    10800,    # 3 h
    14400,    # 4 h
    21600,    # 6 h
    43200,    # 12 h
    86400,    # 24 h
)
MIN_BUCKET_SECONDS = ALLOWED_BUCKET_SECONDS[0]
MAX_BUCKET_SECONDS = ALLOWED_BUCKET_SECONDS[-1]
DEFAULT_TARGET_POINTS = 15_000
DEFAULT_MAX_POINTS = 25_000


@dataclass(frozen=True, slots=True)
class BucketResolution:
    bucket_seconds: int
    estimated_points: int
    required_bucket_seconds: float
    target_points: int
    max_points: int
    target_met: bool


class BucketResolutionLimitError(ValueError):
    """No supported resolution can keep a query below its absolute limit."""

    def __init__(
        self,
        *,
        estimated_points: int,
        max_points: int,
        max_bucket_seconds: int,
    ) -> None:
        super().__init__(
            "Query exceeds the maximum number of points even at the largest "
            "supported bucket. Reduce the window or device count."
        )
        self.estimated_points = estimated_points
        self.max_points = max_points
        self.max_bucket_seconds = max_bucket_seconds


def calculate_bucket_resolution(
    *,
    window_seconds: float,
    device_count: int,
    target_points: int = DEFAULT_TARGET_POINTS,
    max_points: int = DEFAULT_MAX_POINTS,
    min_bucket_seconds: int = MIN_BUCKET_SECONDS,
    max_bucket_seconds: int = MAX_BUCKET_SECONDS,
) -> BucketResolution:
    """Choose the smallest supported bucket that satisfies target or max size."""
    _validate_inputs(
        window_seconds=window_seconds,
        device_count=device_count,
        target_points=target_points,
        max_points=max_points,
        min_bucket_seconds=min_bucket_seconds,
        max_bucket_seconds=max_bucket_seconds,
    )
    allowed_buckets = tuple(
        bucket
        for bucket in ALLOWED_BUCKET_SECONDS
        if min_bucket_seconds <= bucket <= max_bucket_seconds
    )
    if not allowed_buckets:
        raise ValueError("No allowed bucket resolution falls within the requested limits.")

    required_bucket_seconds = (window_seconds * device_count) / target_points
    if device_count == 0:
        return BucketResolution(
            bucket_seconds=allowed_buckets[0],
            estimated_points=0,
            required_bucket_seconds=required_bucket_seconds,
            target_points=target_points,
            max_points=max_points,
            target_met=True,
        )

    target_candidates = (
        bucket_seconds
        for bucket_seconds in allowed_buckets
        if bucket_seconds >= required_bucket_seconds
    )
    for bucket_seconds in target_candidates:
        estimated_points = _estimate_points(
            window_seconds,
            device_count,
            bucket_seconds,
        )
        if estimated_points <= target_points:
            return BucketResolution(
                bucket_seconds=bucket_seconds,
                estimated_points=estimated_points,
                required_bucket_seconds=required_bucket_seconds,
                target_points=target_points,
                max_points=max_points,
                target_met=True,
            )

    for bucket_seconds in allowed_buckets:
        estimated_points = _estimate_points(
            window_seconds,
            device_count,
            bucket_seconds,
        )
        if estimated_points <= max_points:
            return BucketResolution(
                bucket_seconds=bucket_seconds,
                estimated_points=estimated_points,
                required_bucket_seconds=required_bucket_seconds,
                target_points=target_points,
                max_points=max_points,
                target_met=False,
            )

    max_bucket = allowed_buckets[-1]
    raise BucketResolutionLimitError(
        estimated_points=_estimate_points(window_seconds, device_count, max_bucket),
        max_points=max_points,
        max_bucket_seconds=max_bucket,
    )


def _estimate_points(
    window_seconds: float,
    device_count: int,
    bucket_seconds: int,
) -> int:
    return ceil(window_seconds / bucket_seconds) * device_count


def _validate_inputs(
    *,
    window_seconds: float,
    device_count: int,
    target_points: int,
    max_points: int,
    min_bucket_seconds: int,
    max_bucket_seconds: int,
) -> None:
    if isinstance(window_seconds, bool) or not isinstance(window_seconds, (int, float)):
        raise ValueError("window_seconds must be a finite positive number.")
    if not isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("window_seconds must be a finite positive number.")

    for name, value, allow_zero in (
        ("device_count", device_count, True),
        ("target_points", target_points, False),
        ("max_points", max_points, False),
        ("min_bucket_seconds", min_bucket_seconds, False),
        ("max_bucket_seconds", max_bucket_seconds, False),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer.")
        if value < 0 or (not allow_zero and value == 0):
            raise ValueError(f"{name} must be positive.")

    if target_points > max_points:
        raise ValueError("target_points must not exceed max_points.")
    if min_bucket_seconds > max_bucket_seconds:
        raise ValueError("min_bucket_seconds must not exceed max_bucket_seconds.")
