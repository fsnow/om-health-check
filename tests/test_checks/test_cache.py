"""Tests for cache check module."""

from unittest.mock import patch

from om_health_check.checks.cache import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN, STATUS_INFO
from tests.conftest import make_host, make_cluster


class TestCacheMetrics:
    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_all_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (70.0, 68.0),
            "DIRTY_FILL_RATIO": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.hosts) == 1
        checks = section.hosts[0].checks
        assert len(checks) == 4
        assert all(c.status == STATUS_GREEN for c in checks)

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_fill_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (96.0, 90.0),  # > 95 = RED
            "DIRTY_FILL_RATIO": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        cache_check = [c for c in section.hosts[0].checks if c.name == "CACHE_FILL_RATIO"][0]
        assert cache_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_fill_warn(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (85.0, 80.0),  # > 80 warn, < 95 red = WARN
            "DIRTY_FILL_RATIO": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        cache_check = [c for c in section.hosts[0].checks if c.name == "CACHE_FILL_RATIO"][0]
        assert cache_check.status == STATUS_WARN

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_dirty_fill_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (70.0, 68.0),
            "DIRTY_FILL_RATIO": (8.0, 3.0),  # > 5 = RED
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        dirty_check = [c for c in section.hosts[0].checks if c.name == "DIRTY_FILL_RATIO"][0]
        assert dirty_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_cache_bytes_deviation_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (70.0, 68.0),
            "DIRTY_FILL_RATIO": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (20000, 5000),  # 4x > 3.0 = RED (baseline mode)
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, [primary])
        bytes_check = [c for c in section.hosts[0].checks if c.name == "CACHE_BYTES_READ_INTO"][0]
        assert bytes_check.status == STATUS_RED

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_no_data_info(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (None, None),
            "DIRTY_FILL_RATIO": (None, None),
            "CACHE_BYTES_READ_INTO": (None, None),
            "CACHE_BYTES_WRITTEN_FROM": (None, None),
        }
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        assert all(c.status == STATUS_INFO for c in checks)

    @patch("om_health_check.checks.cache.fetch_host_metrics")
    def test_multiple_hosts(self, mock_fetch, mock_client, cluster, three_hosts):
        mock_fetch.return_value = {
            "CACHE_FILL_RATIO": (70.0, 68.0),
            "DIRTY_FILL_RATIO": (2.0, 1.5),
            "CACHE_BYTES_READ_INTO": (5000, 4500),
            "CACHE_BYTES_WRITTEN_FROM": (3000, 2800),
        }
        section = run(mock_client, "p1", cluster, three_hosts)
        assert len(section.hosts) == 3
