"""Tests for cache check module."""

from unittest.mock import patch

from om_health_check.checks.cache import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN, STATUS_INFO
from tests.conftest import make_host, make_cluster


class TestCacheMetrics:
    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_all_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (70.0, 68.0),
            "CACHE_DIRTY_BYTES": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.hosts) == 1
        checks = section.hosts[0].checks
        assert len(checks) == 4
        assert all(c.status == STATUS_GREEN for c in checks)

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_used_spike_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (5000000000, 2000000000),  # 2.5x > 2.0 deviation = RED
            "CACHE_DIRTY_BYTES": (2000, 1500),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        cache_check = [c for c in section.hosts[0].checks if c.name == "CACHE_USED_BYTES"][0]
        assert cache_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_used_normal_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (3000000000, 2800000000),  # 1.07x < 2.0 = GREEN
            "CACHE_DIRTY_BYTES": (2000, 1500),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        cache_check = [c for c in section.hosts[0].checks if c.name == "CACHE_USED_BYTES"][0]
        assert cache_check.status == STATUS_GREEN

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_dirty_bytes_spike_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (3000000000, 2800000000),
            "CACHE_DIRTY_BYTES": (90000000, 20000000),  # 4.5x > 3.0 deviation = RED
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        dirty_check = [c for c in section.hosts[0].checks if c.name == "CACHE_DIRTY_BYTES"][0]
        assert dirty_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_bytes_deviation_red(self, mock_fetch, mock_client, cluster, primary):
        # Above red=1_000_000 AND 4x baseline → both conditions met under mode=AND
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (70.0, 68.0),
            "CACHE_DIRTY_BYTES": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (8_000_000, 2_000_000),  # 4x > 3.0 AND > 1MB/s
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        bytes_check = [c for c in section.hosts[0].checks if c.name == "CACHE_BYTES_READ_INTO"][0]
        assert bytes_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_bytes_low_value_high_dev_green(self, mock_fetch, mock_client, cluster, primary):
        # 4x deviation on a tiny absolute value should NOT fire RED under mode=AND
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (70.0, 68.0),
            "CACHE_DIRTY_BYTES": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (20000, 5000),  # 4x but < 1MB/s
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        bytes_check = [c for c in section.hosts[0].checks if c.name == "CACHE_BYTES_READ_INTO"][0]
        assert bytes_check.status == STATUS_GREEN

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_no_data_info(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (None, None),
            "CACHE_DIRTY_BYTES": (None, None),
            "CACHE_BYTES_READ_INTO": (None, None),
            "CACHE_BYTES_WRITTEN_FROM": (None, None),
        }
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        assert all(c.status == STATUS_INFO for c in checks)

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_multiple_hosts(self, mock_fetch, mock_client, cluster, three_hosts):
        mock_fetch.return_value = {
            "CACHE_USED_BYTES": (70.0, 68.0),
            "CACHE_DIRTY_BYTES": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, three_hosts)
        assert len(section.hosts) == 3
