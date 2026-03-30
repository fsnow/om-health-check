"""Baseline fetch and comparison logic.

Fetches current and 1-week-ago measurements, computes deviation,
and evaluates status using threshold configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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

    if thresh.mode == MODE_ABSOLUTE:
        if abs_red:
            status = STATUS_RED
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN

    elif thresh.mode == MODE_BASELINE:
        status = STATUS_RED if dev_red else STATUS_GREEN

    elif thresh.mode == MODE_AND:
        if abs_red and dev_red:
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
        parts.append(f"— approaching threshold (warn: {thresh.warn})")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Measurement fetching helpers
# ---------------------------------------------------------------------------


def _baseline_time_range() -> tuple[str, str]:
    """Return ISO 8601 start/end for the baseline window (same hour, 1 week ago)."""
    now = datetime.now(timezone.utc)
    baseline_end = now.replace(minute=0, second=0, microsecond=0) - timedelta(weeks=1)
    baseline_start = baseline_end - timedelta(hours=1)
    return baseline_start.isoformat(), baseline_end.isoformat()


def _extract_latest_value(measurements: ProcessMeasurements, metric_name: str) -> float | None:
    """Extract the most recent non-null data point for a metric from measurements."""
    for m in measurements.measurements:
        if m.name == metric_name:
            for dp in reversed(m.data_points):
                if dp.value is not None:
                    return dp.value
    return None


def fetch_host_metrics(
    om: OpsManagerClient,
    project_id: str,
    host_id: str,
    metric_names: list[str],
) -> dict[str, tuple[float | None, float | None]]:
    """Fetch current and baseline values for a list of host metrics.

    Returns dict mapping metric_name -> (current_value, baseline_value).
    """
    baseline_start, baseline_end = _baseline_time_range()

    current = om.measurements.host(
        project_id=project_id,
        host_id=host_id,
        granularity="PT1H",
        period="PT1H",
        metrics=metric_names,
    )

    baseline = om.measurements.host(
        project_id=project_id,
        host_id=host_id,
        granularity="PT1H",
        period=None,
        start=baseline_start,
        end=baseline_end,
        metrics=metric_names,
    )

    result = {}
    for name in metric_names:
        result[name] = (
            _extract_latest_value(current, name),
            _extract_latest_value(baseline, name),
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
    """
    baseline_start, baseline_end = _baseline_time_range()

    current = om.measurements.disk(
        project_id=project_id,
        host_id=host_id,
        partition_name=partition_name,
        granularity="PT1H",
        period="PT1H",
        metrics=metric_names,
    )

    baseline = om.measurements.disk(
        project_id=project_id,
        host_id=host_id,
        partition_name=partition_name,
        granularity="PT1H",
        period=None,
        start=baseline_start,
        end=baseline_end,
        metrics=metric_names,
    )

    result = {}
    for name in metric_names:
        result[name] = (
            _extract_latest_value(current, name),
            _extract_latest_value(baseline, name),
        )
    return result
