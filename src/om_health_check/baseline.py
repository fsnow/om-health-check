"""Baseline fetch and comparison logic.

Fetches current and 1-week-ago measurements, computes deviation,
and evaluates status using threshold configuration.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Suppress per-request error logs from the opsmanager library during fallback fetching;
# we handle and summarize failures ourselves.
logging.getLogger("opsmanager.network").setLevel(logging.CRITICAL)

from opsmanager import OpsManagerClient
from opsmanager.types import Measurement, ProcessMeasurements

from om_health_check.models import STATUS_GREEN, STATUS_INFO, STATUS_RED, STATUS_WARN
from om_health_check.thresholds import (
    DIR_BELOW,
    MODE_ABSOLUTE,
    MODE_AND,
    MODE_BASELINE,
    MODE_OR,
    Threshold,
    get_threshold,
)


@dataclass
class MetricResult:
    """Result of fetching and comparing a single metric against its baseline."""

    metric_name: str
    current_value: float | None
    baseline_value: float | None
    deviation: float | None  # multiplier: current / baseline
    status: str
    threshold: Threshold | None
    message: str


def _compute_deviation(current: float | None, baseline: float | None) -> float | None:
    """Compute deviation as a multiplier (current / baseline)."""
    if current is None or baseline is None:
        return None
    if baseline == 0:
        return None if current == 0 else float("inf")
    return current / baseline


def _crosses_threshold(value: float, thresh: Threshold) -> bool:
    """Check if a value crosses the red threshold in the configured direction."""
    if thresh.red is None:
        return False
    if thresh.direction == DIR_BELOW:
        return value <= thresh.red
    return value >= thresh.red


def _crosses_warn(value: float, thresh: Threshold) -> bool:
    """Check if a value crosses the warn threshold in the configured direction."""
    if thresh.warn is None:
        return False
    if thresh.direction == DIR_BELOW:
        return value <= thresh.warn
    return value >= thresh.warn


def _exceeds_deviation(
    current: float, baseline: float | None, thresh: Threshold
) -> bool:
    """Check if current value exceeds baseline by the configured deviation multiplier."""
    if thresh.deviation is None or baseline is None:
        return False
    if baseline == 0:
        return current != 0
    ratio = current / baseline
    if thresh.direction == DIR_BELOW:
        # For "below" metrics, a deviation means value dropped significantly
        # e.g. deviation=0.3 means RED if current <= baseline * 0.3
        return ratio <= thresh.deviation
    return ratio >= thresh.deviation


def evaluate_metric(
    metric_name: str,
    current_value: float | None,
    baseline_value: float | None,
) -> MetricResult:
    """Evaluate a metric against its threshold and baseline.

    Returns a MetricResult with computed status and message.
    """
    thresh = get_threshold(metric_name)
    deviation = _compute_deviation(current_value, baseline_value)

    if current_value is None:
        return MetricResult(
            metric_name=metric_name,
            current_value=None,
            baseline_value=baseline_value,
            deviation=None,
            status=STATUS_INFO,
            threshold=thresh,
            message="No current data available",
        )

    if thresh is None:
        return MetricResult(
            metric_name=metric_name,
            current_value=current_value,
            baseline_value=baseline_value,
            deviation=deviation,
            status=STATUS_GREEN,
            threshold=None,
            message="No threshold configured",
        )

    abs_red = _crosses_threshold(current_value, thresh)
    abs_warn = _crosses_warn(current_value, thresh)
    dev_red = _exceeds_deviation(current_value, baseline_value, thresh)

    # Baseline missing (cluster too new, no activity, or rollup not computed).
    # Degrade gracefully per mode.
    baseline_missing = baseline_value is None and thresh.deviation is not None

    if thresh.mode == MODE_ABSOLUTE:
        if abs_red:
            status = STATUS_RED
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN

    elif thresh.mode == MODE_BASELINE:
        if baseline_missing:
            # Can't evaluate — no fallback threshold for pure baseline metrics
            return MetricResult(
                metric_name=metric_name,
                current_value=current_value,
                baseline_value=None,
                deviation=None,
                status=STATUS_INFO,
                threshold=thresh,
                message=f"{current_value:,.2f} — no baseline data available",
            )
        status = STATUS_RED if dev_red else STATUS_GREEN

    elif thresh.mode == MODE_AND:
        if baseline_missing:
            # Degrade to threshold-only
            status = STATUS_WARN if abs_red else (STATUS_WARN if abs_warn else STATUS_GREEN)
        elif abs_red and dev_red:
            status = STATUS_RED
        elif abs_red and not dev_red:
            # Above threshold but within normal baseline — suppress to INFO
            status = STATUS_INFO
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN

    elif thresh.mode == MODE_OR:
        if abs_red or dev_red:
            status = STATUS_RED
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN

    else:
        status = STATUS_GREEN

    message = _build_message(metric_name, current_value, baseline_value, deviation, thresh, status)
    if baseline_missing and thresh.mode in (MODE_AND, MODE_OR):
        message += " (no baseline data available)"

    return MetricResult(
        metric_name=metric_name,
        current_value=current_value,
        baseline_value=baseline_value,
        deviation=deviation,
        status=status,
        threshold=thresh,
        message=message,
    )


def _build_message(
    metric_name: str,
    current: float,
    baseline: float | None,
    deviation: float | None,
    thresh: Threshold,
    status: str,
) -> str:
    """Build a human-readable message for a metric result."""
    parts = [f"{current:,.2f}"]

    if baseline is not None and deviation is not None:
        if deviation == float("inf"):
            parts.append("(baseline was 0)")
        else:
            parts.append(f"(baseline: {baseline:,.2f}, {deviation:.1f}x)")

    if status == STATUS_RED:
        if thresh.mode == MODE_BASELINE:
            parts.append("— significant deviation from baseline")
        elif thresh.mode == MODE_AND:
            parts.append(f"— exceeds threshold ({thresh.red}) and deviates from baseline")
        elif thresh.mode == MODE_OR:
            abs_red = _crosses_threshold(current, thresh)
            dev_red = _exceeds_deviation(current, baseline, thresh)
            if abs_red and dev_red:
                parts.append(f"— exceeds threshold ({thresh.red}) and deviates from baseline")
            elif abs_red:
                parts.append(f"— exceeds threshold ({thresh.red})")
            else:
                parts.append("— significant deviation from baseline")
        else:
            parts.append(f"— exceeds threshold ({thresh.red})")
    elif status == STATUS_INFO and thresh.mode == MODE_AND:
        parts.append(f"— above threshold ({thresh.red}) but within normal baseline range")
    elif status == STATUS_WARN:
        if thresh.warn is not None:
            parts.append(f"— approaching threshold (warn: {thresh.warn})")
        elif thresh.red is not None:
            # MODE_AND degraded RED→WARN because baseline is unavailable: above red
            # threshold but we can't confirm deviation, so we cap at WARN.
            parts.append(
                f"— above threshold ({thresh.red}); cannot confirm RED without baseline"
            )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Measurement fetching helpers
# ---------------------------------------------------------------------------


_baseline_lookback: timedelta = timedelta(weeks=1)


def set_baseline_lookback(lookback: timedelta) -> None:
    """Override the baseline lookback window (default 1 week).

    Used during testing against a freshly-built OM instance that doesn't yet
    have 1 week of history. Set to a smaller duration (e.g. timedelta(hours=4))
    to exercise the baseline fetch path against recent data.
    """
    global _baseline_lookback
    _baseline_lookback = lookback


def parse_lookback(s: str) -> timedelta:
    """Parse a lookback string like '7d', '4h', or '30m' into a timedelta."""
    s = s.strip().lower()
    if not s or s[-1] not in ("d", "h", "m"):
        raise ValueError(f"lookback must end in d/h/m (got '{s}')")
    try:
        n = int(s[:-1])
    except ValueError:
        raise ValueError(f"lookback must be an integer followed by d/h/m (got '{s}')")
    if n <= 0:
        raise ValueError(f"lookback must be positive (got '{s}')")
    unit = s[-1]
    if unit == "d":
        return timedelta(days=n)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(minutes=n)


def _baseline_time_range() -> tuple[str, str]:
    """Return ISO 8601 start/end for the baseline window.

    Window is 4 hours wide, ending `_baseline_lookback` ago, aligned to the top
    of the hour. A 4-hour window is the minimum that reliably contains a
    fully-aggregated PT1H bucket for rate-based metrics (CPU %, network bytes/s,
    opcounters, etc.) — OM does not compute the rate aggregation for the most
    recent in-progress bucket, so a narrower window often returns only that
    incomplete bucket and rate metrics come back null.
    """
    now = datetime.now(timezone.utc)
    baseline_end = now.replace(minute=0, second=0, microsecond=0) - _baseline_lookback
    baseline_start = baseline_end - timedelta(hours=4)
    return baseline_start.isoformat(), baseline_end.isoformat()


def _extract_value(measurements: ProcessMeasurements, metric_name: str) -> float | None:
    """Extract the mean of non-null data points for a metric from measurements.

    For current values (PT1M granularity, ~60 samples), this produces a 1-hour average.
    For baseline values (PT1H granularity, 1 sample), the mean equals that single value.
    Averaging makes the current vs baseline comparison apples-to-apples (1h avg vs 1h avg)
    rather than noisy (1m point vs 1h avg).
    """
    for m in measurements.measurements:
        if m.name == metric_name:
            values = [dp.value for dp in m.data_points if dp.value is not None]
            if not values:
                return None
            return sum(values) / len(values)
    return None


_warned_metrics: set[str] = set()


def _fetch_with_fallback(fetch_fn, metric_names: list[str], **kwargs):
    """Try a batched metric fetch; on failure, fall back to per-metric calls.

    Current values are fetched at PT1M granularity over PT1H — finer resolution
    catches recent values even when OM's PT1H rollup lags (e.g., new clusters).
    Baseline values use PT1H — historical data is rolled up.

    Returns a pair (current_measurements, baseline_measurements).
    """
    baseline_start, baseline_end = _baseline_time_range()

    try:
        current = fetch_fn(
            granularity="PT1M", period="PT1H",
            metrics=metric_names, **kwargs,
        )
    except Exception:
        current = _fetch_individually(fetch_fn, metric_names, **kwargs)

    try:
        baseline = fetch_fn(
            granularity="PT1H", period=None,
            start=baseline_start, end=baseline_end,
            metrics=metric_names, **kwargs,
        )
    except Exception:
        baseline = _fetch_individually(
            fetch_fn, metric_names,
            start=baseline_start, end=baseline_end, **kwargs,
        )

    return current, baseline


def _fetch_individually(fetch_fn, metric_names: list[str], start=None, end=None, **kwargs):
    """Fetch metrics one at a time, skipping any that fail."""
    all_measurements = []
    failed = []
    for name in metric_names:
        try:
            if start is not None:
                result = fetch_fn(
                    granularity="PT1H", period=None,
                    start=start, end=end,
                    metrics=[name], **kwargs,
                )
            else:
                result = fetch_fn(
                    granularity="PT1M", period="PT1H",
                    metrics=[name], **kwargs,
                )
            all_measurements.extend(result.measurements)
        except Exception:
            failed.append(name)
    # Only warn once per metric name across the entire run
    new_failures = [m for m in failed if m not in _warned_metrics]
    if new_failures:
        _warned_metrics.update(new_failures)
        print(f"Metrics unavailable: {', '.join(new_failures)}", file=sys.stderr)
    return _FallbackMeasurements(all_measurements)


class _FallbackMeasurements:
    """Minimal stand-in for ProcessMeasurements when built from individual calls."""

    def __init__(self, measurements):
        self.measurements = measurements


def fetch_host_metrics(
    om: OpsManagerClient,
    project_id: str,
    host_id: str,
    metric_names: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """Fetch current and baseline values for a list of host metrics.

    Returns dict mapping metric_name -> (current_value, baseline_value).
    Resilient to invalid metric names — falls back to per-metric fetching.
    """
    current, baseline = _fetch_with_fallback(
        om.measurements.host, metric_names,
        project_id=project_id, host_id=host_id,
    )

    result = {}
    for name in metric_names:
        result[name] = (
            _extract_value(current, name),
            _extract_value(baseline, name),
        )
    return result


def fetch_disk_metrics(
    om: OpsManagerClient,
    project_id: str,
    host_id: str,
    partition_name: str,
    metric_names: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """Fetch current and baseline values for a list of disk metrics.

    Returns dict mapping metric_name -> (current_value, baseline_value).
    Resilient to invalid metric names — falls back to per-metric fetching.
    """
    current, baseline = _fetch_with_fallback(
        om.measurements.disk, metric_names,
        project_id=project_id, host_id=host_id,
        partition_name=partition_name,
    )

    result = {}
    for name in metric_names:
        result[name] = (
            _extract_value(current, name),
            _extract_value(baseline, name),
        )
    return result
