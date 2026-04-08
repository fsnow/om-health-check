"""Tests for compute check module."""

from unittest.mock import patch

from om_health_check.checks.compute import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN, STATUS_INFO


def _green_compute():
    return {
        "SYSTEM_NORMALIZED_CPU_USER": (40.0, 38.0),
        "SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0),
        "PROCESS_NORMALIZED_CPU_USER": (30.0, 28.0),
        "SYSTEM_MEMORY_AVAILABLE": (4000, 4500),
        "MEMORY_RESIDENT": (11000, 10500),
        "SWAP_USAGE_USED": (0, 0),
    }


class TestComputeMetrics:
    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_all_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_compute()
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        assert len(checks) == 6
        assert all(c.status == STATUS_GREEN for c in checks)

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_swap_red(self, mock_fetch, mock_client, cluster, primary):
        metrics = _green_compute()
        metrics["SWAP_USAGE_USED"] = (150, 0)  # > 100 = RED
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return metrics
            return {
                "SYSTEM_NORMALIZED_CPU_STEAL": (None, None),
                "SYSTEM_NORMALIZED_CPU_GUEST": (None, None),
                "SYSTEM_NORMALIZED_CPU_SOFTIRQ": (None, None),
                "SYSTEM_NORMALIZED_CPU_IRQ": (None, None),
                "SYSTEM_NORMALIZED_CPU_NICE": (None, None),
                "SYSTEM_NORMALIZED_CPU_KERNEL": (None, None),
                "SWAP_USAGE_FREE": (500, 2000),
            }
        mock_fetch.side_effect = side_effect
        section = run(mock_client, "p1", cluster, [primary])
        swap_check = [c for c in section.hosts[0].checks if c.name == "SWAP_USAGE_USED"][0]
        assert swap_check.status == STATUS_RED

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_memory_low_red(self, mock_fetch, mock_client, cluster, primary):
        metrics = _green_compute()
        metrics["SYSTEM_MEMORY_AVAILABLE"] = (400, 4000)  # <= 500 = RED
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return metrics
            return {k: (None, None) for k in [
                "SYSTEM_NORMALIZED_CPU_STEAL", "SYSTEM_NORMALIZED_CPU_GUEST",
                "SYSTEM_NORMALIZED_CPU_SOFTIRQ", "SYSTEM_NORMALIZED_CPU_IRQ",
                "SYSTEM_NORMALIZED_CPU_NICE", "SYSTEM_NORMALIZED_CPU_KERNEL",
                "SWAP_USAGE_FREE",
            ]}
        mock_fetch.side_effect = side_effect
        section = run(mock_client, "p1", cluster, [primary])
        mem_check = [c for c in section.hosts[0].checks if c.name == "SYSTEM_MEMORY_AVAILABLE"][0]
        assert mem_check.status == STATUS_RED

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_cpu_warn(self, mock_fetch, mock_client, cluster, primary):
        metrics = _green_compute()
        metrics["SYSTEM_NORMALIZED_CPU_USER"] = (85.0, 80.0)  # > 80 warn, < 95 red
        mock_fetch.return_value = metrics
        section = run(mock_client, "p1", cluster, [primary])
        cpu_check = [c for c in section.hosts[0].checks if c.name == "SYSTEM_NORMALIZED_CPU_USER"][0]
        assert cpu_check.status == STATUS_WARN

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_units_correct(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_compute()
        section = run(mock_client, "p1", cluster, [primary])
        checks = {c.name: c for c in section.hosts[0].checks}
        assert checks["SYSTEM_NORMALIZED_CPU_USER"].units == "%"
        assert checks["SYSTEM_MEMORY_AVAILABLE"].units == "MB"
        assert checks["SWAP_USAGE_USED"].units == "MB"


class TestDeeperAnalysis:
    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_deeper_analysis_triggered_on_red(self, mock_fetch, mock_client, cluster, primary):
        """When a top-level metric is RED, deeper CPU breakdowns should be fetched."""
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Top-level metrics — CPU RED
                return {
                    "SYSTEM_NORMALIZED_CPU_USER": (97.0, 40.0),
                    "SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0),
                    "PROCESS_NORMALIZED_CPU_USER": (50.0, 45.0),
                    "SYSTEM_MEMORY_AVAILABLE": (4000, 4500),
                    "MEMORY_RESIDENT": (11000, 10500),
                    "SWAP_USAGE_USED": (0, 0),
                }
            else:
                # Deeper metrics
                return {
                    "SYSTEM_NORMALIZED_CPU_STEAL": (0.5, 0.3),
                    "SYSTEM_NORMALIZED_CPU_GUEST": (0, 0),
                    "SYSTEM_NORMALIZED_CPU_SOFTIRQ": (0.1, 0.1),
                    "SYSTEM_NORMALIZED_CPU_IRQ": (0, 0),
                    "SYSTEM_NORMALIZED_CPU_NICE": (0, 0),
                    "SYSTEM_NORMALIZED_CPU_KERNEL": (3.0, 2.5),
                    "SWAP_USAGE_FREE": (2000, 2000),
                }

        mock_fetch.side_effect = side_effect
        section = run(mock_client, "p1", cluster, [primary])

        checks = section.hosts[0].checks
        # Should have top-level checks + deeper INFO checks
        info_checks = [c for c in checks if c.status == STATUS_INFO]
        assert len(info_checks) > 0
        deeper_names = {c.name for c in info_checks}
        assert "SYSTEM_NORMALIZED_CPU_STEAL" in deeper_names
        assert "SYSTEM_NORMALIZED_CPU_KERNEL" in deeper_names

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_no_deeper_when_all_green(self, mock_fetch, mock_client, cluster, primary):
        """When all top-level metrics are GREEN, no deeper analysis."""
        mock_fetch.return_value = _green_compute()
        section = run(mock_client, "p1", cluster, [primary])

        checks = section.hosts[0].checks
        # Only top-level checks, no deeper INFO breakdowns
        assert len(checks) == 6
        assert mock_fetch.call_count == 1  # Only one call, no deeper fetch

    @patch("om_health_check.checks.compute.fetch_host_metrics")
    def test_deeper_skips_none_values(self, mock_fetch, mock_client, cluster, primary):
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "SYSTEM_NORMALIZED_CPU_USER": (97.0, 40.0),
                    "SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0),
                    "PROCESS_NORMALIZED_CPU_USER": (50.0, 45.0),
                    "SYSTEM_MEMORY_AVAILABLE": (4000, 4500),
                    "MEMORY_RESIDENT": (11000, 10500),
                    "SWAP_USAGE_USED": (0, 0),
                }
            return {k: (None, None) for k in [
                "SYSTEM_NORMALIZED_CPU_STEAL", "SYSTEM_NORMALIZED_CPU_GUEST",
                "SYSTEM_NORMALIZED_CPU_SOFTIRQ", "SYSTEM_NORMALIZED_CPU_IRQ",
                "SYSTEM_NORMALIZED_CPU_NICE", "SYSTEM_NORMALIZED_CPU_KERNEL",
                "SWAP_USAGE_FREE",
            ]}
        mock_fetch.side_effect = side_effect
        section = run(mock_client, "p1", cluster, [primary])
        # Only top-level checks; deeper metrics all None so skipped
        assert len(section.hosts[0].checks) == 6
