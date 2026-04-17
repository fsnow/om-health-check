"""Unit tests for baseline evaluation logic."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from om_health_check.baseline import (
    evaluate_metric,
    _compute_deviation,
    _crosses_threshold,
    _crosses_warn,
    _exceeds_deviation,
    _fetch_with_fallback,
    _fetch_individually,
    _FallbackMeasurements,
    _extract_value,
    fetch_host_metrics,
    fetch_disk_metrics,
)
from om_health_check.models import STATUS_GREEN, STATUS_INFO, STATUS_RED, STATUS_WARN
from om_health_check.thresholds import Threshold, DIR_ABOVE, DIR_BELOW, MODE_ABSOLUTE, MODE_BASELINE, MODE_AND, MODE_OR


# ---------------------------------------------------------------------------
# _compute_deviation
# ---------------------------------------------------------------------------

class TestComputeDeviation:
    def test_normal(self):
        assert _compute_deviation(100, 50) == 2.0

    def test_same_value(self):
        assert _compute_deviation(50, 50) == 1.0

    def test_decrease(self):
        assert _compute_deviation(25, 50) == 0.5

    def test_zero_baseline_zero_current(self):
        assert _compute_deviation(0, 0) is None

    def test_zero_baseline_nonzero_current(self):
        assert _compute_deviation(10, 0) == float("inf")

    def test_current_none(self):
        assert _compute_deviation(None, 50) is None

    def test_baseline_none(self):
        assert _compute_deviation(50, None) is None

    def test_both_none(self):
        assert _compute_deviation(None, None) is None


# ---------------------------------------------------------------------------
# _crosses_threshold
# ---------------------------------------------------------------------------

class TestCrossesThreshold:
    def test_above_at_threshold(self):
        t = Threshold(red=95.0, direction=DIR_ABOVE)
        assert _crosses_threshold(95.0, t) is True

    def test_above_over_threshold(self):
        t = Threshold(red=95.0, direction=DIR_ABOVE)
        assert _crosses_threshold(97.0, t) is True

    def test_above_under_threshold(self):
        t = Threshold(red=95.0, direction=DIR_ABOVE)
        assert _crosses_threshold(90.0, t) is False

    def test_below_at_threshold(self):
        t = Threshold(red=24, direction=DIR_BELOW)
        assert _crosses_threshold(24, t) is True

    def test_below_under_threshold(self):
        t = Threshold(red=24, direction=DIR_BELOW)
        assert _crosses_threshold(20, t) is True

    def test_below_over_threshold(self):
        t = Threshold(red=24, direction=DIR_BELOW)
        assert _crosses_threshold(48, t) is False

    def test_no_red_threshold(self):
        t = Threshold(red=None, direction=DIR_ABOVE)
        assert _crosses_threshold(999, t) is False


# ---------------------------------------------------------------------------
# _crosses_warn
# ---------------------------------------------------------------------------

class TestCrossesWarn:
    def test_above_at_warn(self):
        t = Threshold(warn=80.0, direction=DIR_ABOVE)
        assert _crosses_warn(80.0, t) is True

    def test_above_under_warn(self):
        t = Threshold(warn=80.0, direction=DIR_ABOVE)
        assert _crosses_warn(70.0, t) is False

    def test_below_at_warn(self):
        t = Threshold(warn=36, direction=DIR_BELOW)
        assert _crosses_warn(36, t) is True

    def test_below_over_warn(self):
        t = Threshold(warn=36, direction=DIR_BELOW)
        assert _crosses_warn(48, t) is False

    def test_no_warn_threshold(self):
        t = Threshold(warn=None, direction=DIR_ABOVE)
        assert _crosses_warn(999, t) is False


# ---------------------------------------------------------------------------
# _exceeds_deviation
# ---------------------------------------------------------------------------

class TestExceedsDeviation:
    def test_above_exceeds(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(100, 40, t) is True  # 2.5x

    def test_above_within(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(70, 40, t) is False  # 1.75x

    def test_above_exact(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(80, 40, t) is True  # exactly 2.0x

    def test_below_exceeds(self):
        # deviation=0.3 means RED if current/baseline <= 0.3
        t = Threshold(deviation=0.3, direction=DIR_BELOW)
        assert _exceeds_deviation(100, 1000, t) is True  # 0.1x

    def test_below_within(self):
        t = Threshold(deviation=0.3, direction=DIR_BELOW)
        assert _exceeds_deviation(500, 1000, t) is False  # 0.5x

    def test_zero_baseline_nonzero_current(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(10, 0, t) is True

    def test_zero_baseline_zero_current(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(0, 0, t) is False

    def test_no_deviation_configured(self):
        t = Threshold(deviation=None, direction=DIR_ABOVE)
        assert _exceeds_deviation(999, 1, t) is False

    def test_baseline_none(self):
        t = Threshold(deviation=2.0, direction=DIR_ABOVE)
        assert _exceeds_deviation(100, None, t) is False


# ---------------------------------------------------------------------------
# evaluate_metric — MODE_ABSOLUTE
# ---------------------------------------------------------------------------

class TestModeAbsolute:
    def test_above_red(self):
        r = evaluate_metric("DISK_PARTITION_IOPS_READ", 960, 900)
        assert r.status == STATUS_RED

    def test_above_green(self):
        r = evaluate_metric("DISK_PARTITION_IOPS_READ", 800, 750)
        assert r.status == STATUS_GREEN

    def test_below_red(self):
        r = evaluate_metric("OPLOG_MASTER_TIME", 20, 100)
        assert r.status == STATUS_RED

    def test_below_warn(self):
        r = evaluate_metric("OPLOG_MASTER_TIME", 30, 100)
        assert r.status == STATUS_WARN

    def test_below_green(self):
        r = evaluate_metric("OPLOG_MASTER_TIME", 72, 100)
        assert r.status == STATUS_GREEN

    def test_baseline_is_informational(self):
        # Even with huge deviation, absolute mode ignores baseline for status
        r = evaluate_metric("DISK_PARTITION_IOPS_READ", 700, 100)
        assert r.status == STATUS_GREEN  # 7x baseline but under threshold

    def test_replication_lag_red(self):
        r = evaluate_metric("OPLOG_REPLICATION_LAG_TIME", 120, 5)
        assert r.status == STATUS_RED

    def test_replication_lag_green(self):
        r = evaluate_metric("OPLOG_REPLICATION_LAG_TIME", 2, 3)
        assert r.status == STATUS_GREEN

    def test_swap_red(self):
        r = evaluate_metric("SWAP_USAGE_USED", 150, 0)
        assert r.status == STATUS_RED

    def test_swap_green(self):
        r = evaluate_metric("SWAP_USAGE_USED", 0, 0)
        assert r.status == STATUS_GREEN


# ---------------------------------------------------------------------------
# evaluate_metric — MODE_BASELINE
# ---------------------------------------------------------------------------

class TestModeBaseline:
    def test_spike_red(self):
        r = evaluate_metric("OPCOUNTER_QUERY", 40000, 10000)  # 4x
        assert r.status == STATUS_RED

    def test_normal_green(self):
        r = evaluate_metric("OPCOUNTER_QUERY", 12000, 10000)  # 1.2x
        assert r.status == STATUS_GREEN

    def test_exact_threshold(self):
        r = evaluate_metric("OPCOUNTER_QUERY", 30000, 10000)  # 3.0x = deviation
        assert r.status == STATUS_RED

    def test_just_under(self):
        r = evaluate_metric("OPCOUNTER_QUERY", 29000, 10000)  # 2.9x
        assert r.status == STATUS_GREEN

    def test_no_baseline(self):
        # Cluster < 1 week old — explicit INFO with message
        r = evaluate_metric("OPCOUNTER_QUERY", 10000, None)
        assert r.status == STATUS_INFO
        assert "no baseline yet" in r.message.lower()

    def test_zero_baseline_nonzero_current(self):
        r = evaluate_metric("OPCOUNTER_QUERY", 100, 0)
        assert r.status == STATUS_RED

    def test_network_spike(self):
        r = evaluate_metric("NETWORK_BYTES_IN", 150000, 40000)  # 3.75x
        assert r.status == STATUS_RED

    def test_network_normal(self):
        r = evaluate_metric("NETWORK_BYTES_IN", 50000, 40000)  # 1.25x
        assert r.status == STATUS_GREEN


# ---------------------------------------------------------------------------
# evaluate_metric — MODE_AND
# ---------------------------------------------------------------------------

class TestModeAnd:
    def test_both_conditions_red(self):
        # CPU 97%, baseline 40% -> above 95 threshold AND 2.4x > 2.0 deviation
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 97.0, 40.0)
        assert r.status == STATUS_RED

    def test_threshold_crossed_baseline_normal_info(self):
        # CPU 97%, baseline 95% -> above threshold but 1.02x < 2.0 deviation
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 97.0, 95.0)
        assert r.status == STATUS_INFO

    def test_below_threshold_green(self):
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 50.0, 45.0)
        assert r.status == STATUS_GREEN

    def test_warn_without_deviation(self):
        # Between warn (80) and red (95), warn fires regardless of deviation
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 85.0, 80.0)
        assert r.status == STATUS_WARN

    def test_iowait_both(self):
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_IOWAIT", 25.0, 5.0)  # > 20 and 5x > 3.0
        assert r.status == STATUS_RED

    def test_iowait_threshold_only(self):
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_IOWAIT", 22.0, 18.0)  # > 20 but 1.2x < 3.0
        assert r.status == STATUS_INFO

    def test_query_targeting_and_red(self):
        r = evaluate_metric("QUERY_TARGETING_SCANNED_PER_RETURNED", 1500, 500)  # > 1000 and 3x > 2.0
        assert r.status == STATUS_RED

    def test_query_targeting_and_suppressed(self):
        r = evaluate_metric("QUERY_TARGETING_SCANNED_PER_RETURNED", 1200, 1100)  # > 1000 but 1.09x < 2.0
        assert r.status == STATUS_INFO


# ---------------------------------------------------------------------------
# evaluate_metric — MODE_OR
# ---------------------------------------------------------------------------

class TestModeOr:
    def test_threshold_only(self):
        r = evaluate_metric("CONNECTIONS", 26000, 20000)  # > 25000, 1.3x < 2.0
        assert r.status == STATUS_RED

    def test_deviation_only(self):
        r = evaluate_metric("CONNECTIONS", 15000, 5000)  # < 25000, 3.0x >= 2.0
        assert r.status == STATUS_RED

    def test_both(self):
        r = evaluate_metric("CONNECTIONS", 26000, 10000)  # > 25000 and 2.6x >= 2.0
        assert r.status == STATUS_RED

    def test_neither_green(self):
        r = evaluate_metric("CONNECTIONS", 8000, 5000)  # < 25000, 1.6x < 2.0
        assert r.status == STATUS_GREEN

    def test_warn(self):
        r = evaluate_metric("CONNECTIONS", 21000, 18000)  # > 20000 warn, 1.17x < 2.0, < 25000 red
        assert r.status == STATUS_WARN

    def test_memory_low_absolute(self):
        # SYSTEM_MEMORY_AVAILABLE: red=500, dir=below, deviation=0.3, mode=or
        r = evaluate_metric("SYSTEM_MEMORY_AVAILABLE", 400, 2000)
        assert r.status == STATUS_RED

    def test_memory_low_deviation(self):
        # 200 / 2000 = 0.1 <= 0.3 deviation
        r = evaluate_metric("SYSTEM_MEMORY_AVAILABLE", 200, 2000)
        assert r.status == STATUS_RED

    def test_memory_ok(self):
        r = evaluate_metric("SYSTEM_MEMORY_AVAILABLE", 4000, 4500)
        assert r.status == STATUS_GREEN

    def test_disk_latency_threshold(self):
        r = evaluate_metric("DISK_PARTITION_LATENCY_READ", 12.0, 3.0)  # > 10 and 4x > 3.0
        assert r.status == STATUS_RED

    def test_disk_latency_deviation_only(self):
        r = evaluate_metric("DISK_PARTITION_LATENCY_READ", 7.0, 2.0)  # < 10 but 3.5x > 3.0
        assert r.status == STATUS_RED

    def test_disk_latency_green(self):
        r = evaluate_metric("DISK_PARTITION_LATENCY_READ", 3.0, 2.5)  # < 10, 1.2x < 3.0
        assert r.status == STATUS_GREEN

    def test_queue_readers_spike(self):
        r = evaluate_metric("GLOBAL_LOCK_CURRENT_QUEUE_READERS", 8, 2)  # < 10 but 4x > 3.0
        assert r.status == STATUS_RED

    def test_queue_readers_green(self):
        r = evaluate_metric("GLOBAL_LOCK_CURRENT_QUEUE_READERS", 2, 2)
        assert r.status == STATUS_GREEN

    def test_op_execution_time_threshold(self):
        r = evaluate_metric("OP_EXECUTION_TIME_READS", 120, 50)  # > 100
        assert r.status == STATUS_RED

    def test_op_execution_time_deviation(self):
        r = evaluate_metric("OP_EXECUTION_TIME_READS", 60, 25)  # < 100 but 2.4x >= 2.0
        assert r.status == STATUS_RED

    def test_op_execution_time_green(self):
        r = evaluate_metric("OP_EXECUTION_TIME_READS", 30, 25)
        assert r.status == STATUS_GREEN


# ---------------------------------------------------------------------------
# evaluate_metric — missing baseline (cluster < 1 week old)
# ---------------------------------------------------------------------------


class TestMissingBaseline:
    def test_baseline_mode_info(self):
        # MODE_BASELINE with no baseline → INFO with explanation
        r = evaluate_metric("OPCOUNTER_QUERY", 5000, None)
        assert r.status == STATUS_INFO
        assert "no baseline yet" in r.message.lower()

    def test_and_mode_degrades_to_threshold_over(self):
        # MODE_AND, over threshold, no baseline → WARN (can't confirm deviation)
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 97.0, None)
        assert r.status == STATUS_WARN
        assert "no baseline yet" in r.message.lower()

    def test_and_mode_degrades_to_threshold_under(self):
        # MODE_AND, under threshold, no baseline → GREEN
        r = evaluate_metric("SYSTEM_NORMALIZED_CPU_USER", 40.0, None)
        assert r.status == STATUS_GREEN

    def test_or_mode_threshold_still_works(self):
        # MODE_OR with threshold crossed → still RED even without baseline
        r = evaluate_metric("CONNECTIONS", 30000, None)
        assert r.status == STATUS_RED
        assert "no baseline yet" in r.message.lower()

    def test_or_mode_under_threshold_green(self):
        # MODE_OR under threshold, no baseline → GREEN (can't check deviation)
        r = evaluate_metric("CONNECTIONS", 1000, None)
        assert r.status == STATUS_GREEN

    def test_absolute_mode_unaffected(self):
        # MODE_ABSOLUTE never needs baseline
        r = evaluate_metric("SWAP_USAGE_USED", 50, None)
        assert r.status == STATUS_GREEN


# ---------------------------------------------------------------------------
# evaluate_metric — edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_current_none(self):
        r = evaluate_metric("CONNECTIONS", None, 5000)
        assert r.status == STATUS_INFO
        assert "No current data" in r.message

    def test_no_threshold_configured(self):
        r = evaluate_metric("TOTALLY_UNKNOWN_METRIC", 100, 50)
        assert r.status == STATUS_GREEN
        assert r.threshold is None

    def test_both_none(self):
        r = evaluate_metric("CONNECTIONS", None, None)
        assert r.status == STATUS_INFO

    def test_deviation_in_result(self):
        r = evaluate_metric("CONNECTIONS", 10000, 5000)
        assert r.deviation == 2.0

    def test_deviation_none_when_no_baseline(self):
        r = evaluate_metric("CONNECTIONS", 10000, None)
        assert r.deviation is None

    def test_message_contains_value(self):
        r = evaluate_metric("CONNECTIONS", 10000, 5000)
        assert "10,000" in r.message

    def test_message_contains_baseline(self):
        r = evaluate_metric("CONNECTIONS", 10000, 5000)
        assert "5,000" in r.message
        assert "2.0x" in r.message


# ---------------------------------------------------------------------------
# _extract_value
# ---------------------------------------------------------------------------


class TestExtractValue:
    def test_single_non_null(self):
        dp1 = MagicMock(value=None)
        dp2 = MagicMock(value=42.0)
        dp3 = MagicMock(value=None)
        m = MagicMock(data_points=[dp1, dp2, dp3])
        m.name = "CPU"
        measurements = MagicMock(measurements=[m])
        assert _extract_value(measurements, "CPU") == 42.0

    def test_returns_none_for_missing_metric(self):
        m = MagicMock(data_points=[])
        m.name = "CPU"
        measurements = MagicMock(measurements=[m])
        assert _extract_value(measurements, "DISK") is None

    def test_returns_none_for_all_null_datapoints(self):
        dp1 = MagicMock(value=None)
        dp2 = MagicMock(value=None)
        m = MagicMock(data_points=[dp1, dp2])
        m.name = "CPU"
        measurements = MagicMock(measurements=[m])
        assert _extract_value(measurements, "CPU") is None

    def test_averages_non_null_values(self):
        # Hourly average over PT1M samples: 10, 20, 30 -> 20.0
        dp1 = MagicMock(value=10.0)
        dp2 = MagicMock(value=20.0)
        dp3 = MagicMock(value=30.0)
        m = MagicMock(data_points=[dp1, dp2, dp3])
        m.name = "CPU"
        measurements = MagicMock(measurements=[m])
        assert _extract_value(measurements, "CPU") == 20.0

    def test_averages_skipping_nulls(self):
        dp1 = MagicMock(value=10.0)
        dp2 = MagicMock(value=None)
        dp3 = MagicMock(value=30.0)
        m = MagicMock(data_points=[dp1, dp2, dp3])
        m.name = "CPU"
        measurements = MagicMock(measurements=[m])
        assert _extract_value(measurements, "CPU") == 20.0


# ---------------------------------------------------------------------------
# _FallbackMeasurements
# ---------------------------------------------------------------------------


class TestFallbackMeasurements:
    def test_stores_measurements(self):
        items = [MagicMock(), MagicMock()]
        fb = _FallbackMeasurements(items)
        assert fb.measurements is items
        assert len(fb.measurements) == 2


# ---------------------------------------------------------------------------
# _fetch_individually
# ---------------------------------------------------------------------------


class TestFetchIndividually:
    def test_collects_successful_metrics(self):
        m1 = MagicMock()
        m2 = MagicMock()
        result1 = MagicMock(measurements=[m1])
        result2 = MagicMock(measurements=[m2])
        fetch_fn = MagicMock(side_effect=[result1, result2])

        fb = _fetch_individually(fetch_fn, ["A", "B"])
        assert len(fb.measurements) == 2
        assert fetch_fn.call_count == 2

    def test_skips_failed_metrics(self, capsys):
        from om_health_check.baseline import _warned_metrics
        _warned_metrics.discard("Y1")
        _warned_metrics.discard("Y2")
        result1 = MagicMock(measurements=[MagicMock()])
        fetch_fn = MagicMock(side_effect=[result1, Exception("invalid metric")])

        fb = _fetch_individually(fetch_fn, ["Y1", "Y2"])
        assert len(fb.measurements) == 1
        captured = capsys.readouterr()
        assert "Y2" in captured.err

    def test_all_fail(self, capsys):
        from om_health_check.baseline import _warned_metrics
        _warned_metrics.discard("X1")
        _warned_metrics.discard("X2")
        _warned_metrics.discard("X3")
        fetch_fn = MagicMock(side_effect=Exception("network error"))
        fb = _fetch_individually(fetch_fn, ["X1", "X2", "X3"])
        assert len(fb.measurements) == 0
        captured = capsys.readouterr()
        assert "X1" in captured.err
        assert "X2" in captured.err
        assert "X3" in captured.err

    def test_baseline_params_passed(self):
        result = MagicMock(measurements=[])
        fetch_fn = MagicMock(return_value=result)

        _fetch_individually(fetch_fn, ["A"], start="2026-01-01", end="2026-01-02")
        call_kwargs = fetch_fn.call_args[1]
        assert call_kwargs["start"] == "2026-01-01"
        assert call_kwargs["end"] == "2026-01-02"
        assert call_kwargs["period"] is None

    def test_current_params_passed(self):
        result = MagicMock(measurements=[])
        fetch_fn = MagicMock(return_value=result)

        _fetch_individually(fetch_fn, ["A"])
        call_kwargs = fetch_fn.call_args[1]
        assert call_kwargs["period"] == "PT1H"
        assert "start" not in call_kwargs


# ---------------------------------------------------------------------------
# _fetch_with_fallback
# ---------------------------------------------------------------------------


class TestFetchWithFallback:
    @patch("om_health_check.baseline._baseline_time_range")
    def test_batch_success(self, mock_time):
        mock_time.return_value = ("2026-01-01T00:00:00", "2026-01-01T01:00:00")
        current_result = MagicMock()
        baseline_result = MagicMock()
        fetch_fn = MagicMock(side_effect=[current_result, baseline_result])

        current, baseline = _fetch_with_fallback(fetch_fn, ["A", "B"])
        assert current is current_result
        assert baseline is baseline_result
        assert fetch_fn.call_count == 2

    @patch("om_health_check.baseline._fetch_individually")
    @patch("om_health_check.baseline._baseline_time_range")
    def test_current_batch_fails_falls_back(self, mock_time, mock_indiv):
        mock_time.return_value = ("2026-01-01T00:00:00", "2026-01-01T01:00:00")
        fallback = _FallbackMeasurements([])
        baseline_result = MagicMock()
        fetch_fn = MagicMock(side_effect=[Exception("invalid metric"), baseline_result])
        mock_indiv.return_value = fallback

        current, baseline = _fetch_with_fallback(fetch_fn, ["A", "B"])
        assert current is fallback
        assert baseline is baseline_result
        mock_indiv.assert_called_once()

    @patch("om_health_check.baseline._fetch_individually")
    @patch("om_health_check.baseline._baseline_time_range")
    def test_baseline_batch_fails_falls_back(self, mock_time, mock_indiv, capsys):
        mock_time.return_value = ("2026-01-01T00:00:00", "2026-01-01T01:00:00")
        current_result = MagicMock()
        fallback = _FallbackMeasurements([])
        fetch_fn = MagicMock(side_effect=[current_result, Exception("invalid metric")])
        mock_indiv.return_value = fallback

        current, baseline = _fetch_with_fallback(fetch_fn, ["A", "B"])
        assert current is current_result
        assert baseline is fallback


# ---------------------------------------------------------------------------
# fetch_host_metrics / fetch_disk_metrics
# ---------------------------------------------------------------------------


class TestFetchHostMetrics:
    @patch("om_health_check.baseline._fetch_with_fallback")
    def test_returns_metric_dict(self, mock_fallback):
        dp = MagicMock(value=42.0)
        m = MagicMock(data_points=[dp])
        m.name = "CPU"
        current = MagicMock(measurements=[m])
        baseline = MagicMock(measurements=[])
        mock_fallback.return_value = (current, baseline)

        result = fetch_host_metrics(MagicMock(), "p1", "h1", ["CPU"])
        assert result["CPU"] == (42.0, None)

    @patch("om_health_check.baseline._fetch_with_fallback")
    def test_missing_metric_returns_none_pair(self, mock_fallback):
        current = MagicMock(measurements=[])
        baseline = MagicMock(measurements=[])
        mock_fallback.return_value = (current, baseline)

        result = fetch_host_metrics(MagicMock(), "p1", "h1", ["MISSING"])
        assert result["MISSING"] == (None, None)


class TestFetchDiskMetrics:
    @patch("om_health_check.baseline._fetch_with_fallback")
    def test_passes_partition_name(self, mock_fallback):
        current = MagicMock(measurements=[])
        baseline = MagicMock(measurements=[])
        mock_fallback.return_value = (current, baseline)

        fetch_disk_metrics(MagicMock(), "p1", "h1", "nvme0n1", ["DISK_IOPS"])
        call_kwargs = mock_fallback.call_args[1]
        assert call_kwargs["partition_name"] == "nvme0n1"
