"""Tests for replication check module."""

from unittest.mock import patch

from om_health_check.checks.replication import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN
from tests.conftest import make_host, make_cluster


class TestReplicationHostFiltering:
    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_primary_gets_oplog_metrics(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.hosts) == 1
        metric_names = {c.name for c in section.hosts[0].checks}
        assert "OPLOG_MASTER_TIME" in metric_names
        assert "OPLOG_RATE_GB_PER_HOUR" in metric_names

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_secondary_gets_lag_and_oplog(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_REPLICATION_LAG_TIME": (0.5, 0.3),
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        assert len(section.hosts) == 1
        metric_names = {c.name for c in section.hosts[0].checks}
        assert "OPLOG_REPLICATION_LAG_TIME" in metric_names

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_arbiter_skipped(self, mock_fetch, mock_client):
        cluster = make_cluster()
        arbiter = make_host(replica_state_name="ARBITER", type_name="REPLICA_ARBITER")
        section = run(mock_client, "p1", cluster, [arbiter])
        assert len(section.hosts) == 0
        mock_fetch.assert_not_called()

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_mongos_skipped(self, mock_fetch, mock_client):
        cluster = make_cluster()
        mongos = make_host(replica_state_name=None, type_name="MONGOS")
        section = run(mock_client, "p1", cluster, [mongos])
        assert len(section.hosts) == 0
        mock_fetch.assert_not_called()

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_primary_and_secondaries(self, mock_fetch, mock_client):
        def side_effect(*args, **kwargs):
            metrics = kwargs.get("metric_names", args[3] if len(args) > 3 else [])
            # The code passes metric_names as positional arg
            return {name: (100, 100) for name in args[3]}

        mock_fetch.side_effect = side_effect
        cluster = make_cluster()
        hosts = [
            make_host(host_id="h1", replica_state_name="PRIMARY"),
            make_host(host_id="h2", hostname="mongo2.example.com", replica_state_name="SECONDARY"),
            make_host(host_id="h3", hostname="mongo3.example.com", replica_state_name="SECONDARY"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        assert len(section.hosts) == 3


class TestReplicationStatus:
    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_oplog_window_red(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (20, 100),  # <= 24 = RED (DIR_BELOW)
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        oplog_check = [c for c in section.hosts[0].checks if c.name == "OPLOG_MASTER_TIME"][0]
        assert oplog_check.status == STATUS_RED

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_oplog_window_warn(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_MASTER_TIME": (30, 100),  # <= 36 warn = WARN
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        oplog_check = [c for c in section.hosts[0].checks if c.name == "OPLOG_MASTER_TIME"][0]
        assert oplog_check.status == STATUS_WARN

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_replication_lag_red(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_REPLICATION_LAG_TIME": (120, 5),  # > 60 = RED
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        lag_check = [c for c in section.hosts[0].checks if c.name == "OPLOG_REPLICATION_LAG_TIME"][0]
        assert lag_check.status == STATUS_RED

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_replication_lag_warn(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_REPLICATION_LAG_TIME": (15, 5),  # > 10 warn, < 60 red = WARN
            "OPLOG_MASTER_TIME": (168, 170),
            "OPLOG_RATE_GB_PER_HOUR": (0.5, 0.4),
        }
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        lag_check = [c for c in section.hosts[0].checks if c.name == "OPLOG_REPLICATION_LAG_TIME"][0]
        assert lag_check.status == STATUS_WARN
