"""Tests for connections check module."""

from unittest.mock import patch

from om_health_check.checks.connections import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN, STATUS_INFO


class TestZeroConnections:
    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_zero_is_green_upstream_message(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (0, 5000),
            "OP_EXECUTION_TIME_READS": (None, None),
            "OP_EXECUTION_TIME_WRITES": (None, None),
        }
        section = run(mock_client, "p1", cluster, [primary])
        conn_check = section.hosts[0].checks[0]
        assert conn_check.status == STATUS_GREEN
        assert "upstream" in conn_check.message


class TestConnectionStatus:
    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_warn(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (21000, 18000),  # > 20000 warn, < 25000 red, 1.17x < 2.0 dev
            "OP_EXECUTION_TIME_READS": (10, 12),
            "OP_EXECUTION_TIME_WRITES": (8, 10),
        }
        section = run(mock_client, "p1", cluster, [primary])
        conn_check = section.hosts[0].checks[0]
        assert conn_check.status == STATUS_WARN

    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_none_current_info(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (None, 5000),
            "OP_EXECUTION_TIME_READS": (None, None),
            "OP_EXECUTION_TIME_WRITES": (None, None),
        }
        section = run(mock_client, "p1", cluster, [primary])
        conn_check = section.hosts[0].checks[0]
        assert conn_check.status == STATUS_INFO

    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_writes_only_latency_correlation(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (26000, 10000),  # RED
            "OP_EXECUTION_TIME_READS": (10, 12),  # normal
            "OP_EXECUTION_TIME_WRITES": (120, 25),  # RED
        }
        section = run(mock_client, "p1", cluster, [primary])
        correlation = [c for c in section.hosts[0].checks if c.name == "Connection storm correlation"]
        assert len(correlation) == 1


class TestConnectionStormCorrelation:
    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_spike_with_latency_shows_correlation(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (26000, 10000),
            "OP_EXECUTION_TIME_READS": (150, 30),
            "OP_EXECUTION_TIME_WRITES": (120, 25),
        }
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        conn_check = checks[0]
        assert conn_check.status == STATUS_RED
        correlation = [c for c in checks if c.name == "Connection storm correlation"]
        assert len(correlation) == 1
        assert correlation[0].status == STATUS_INFO
        assert "symptom" in correlation[0].message

    @patch("om_health_check.checks.connections.fetch_host_metrics")
    def test_spike_without_latency_no_correlation(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = {
            "CONNECTIONS": (26000, 10000),
            "OP_EXECUTION_TIME_READS": (10, 12),
            "OP_EXECUTION_TIME_WRITES": (8, 10),
        }
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        correlation = [c for c in checks if c.name == "Connection storm correlation"]
        assert len(correlation) == 0
