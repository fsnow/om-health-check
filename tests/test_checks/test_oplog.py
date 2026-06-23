"""Tests for the Oplog section (window + write rate, per replica member)."""

from unittest.mock import patch

from om_health_check.checks.oplog import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN
from tests.conftest import make_host, make_cluster


class TestOplogHostFiltering:
    @patch("om_health_check.checks.oplog.fetch_host_metrics")
    def test_primary_and_secondary_get_oplog_checks(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        hosts = [
            make_host(host_id="h1", replica_state_name="PRIMARY"),
            make_host(host_id="h2", hostname="mongo2.example.com", replica_state_name="SECONDARY"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        assert len(section.hosts) == 2

    @patch("om_health_check.checks.oplog.fetch_host_metrics")
    def test_arbiter_and_mongos_skipped(self, mock_fetch, mock_client):
        cluster = make_cluster()
        hosts = [
            make_host(replica_state_name="ARBITER", type_name="REPLICA_ARBITER"),
            make_host(replica_state_name=None, type_name="SHARD_MONGOS"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        assert len(section.hosts) == 0
        mock_fetch.assert_not_called()


class TestOplogStatus:
    @patch("om_health_check.checks.oplog.fetch_host_metrics")
    def test_window_red(self, mock_fetch, mock_client):
        # OPLOG_MASTER_TIME 20h <= 24h red (DIR_BELOW)
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (20, 100),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        window = [c for c in section.hosts[0].checks if c.name == "OPLOG_MASTER_TIME"][0]
        assert window.status == STATUS_RED

    @patch("om_health_check.checks.oplog.fetch_host_metrics")
    def test_window_warn(self, mock_fetch, mock_client):
        # 30h between red=24 and warn=36 (DIR_BELOW) → WARN
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (30, 100),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        window = [c for c in section.hosts[0].checks if c.name == "OPLOG_MASTER_TIME"][0]
        assert window.status == STATUS_WARN

    @patch("om_health_check.checks.oplog.fetch_host_metrics")
    def test_rate_informational_only(self, mock_fetch, mock_client):
        # OPLOG_RATE has no red/warn — always GREEN regardless of value.
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (99.0, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        rate = [c for c in section.hosts[0].checks if c.name == "OPLOG_RATE_GB_PER_HOUR"][0]
        assert rate.status == STATUS_GREEN
