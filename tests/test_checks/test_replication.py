"""Tests for the Replication section (per-secondary lag against primary).

Oplog window + rate live in test_oplog.py — they're a separate section now.
"""

from unittest.mock import patch

from om_health_check.checks.replication import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN
from tests.conftest import make_host, make_cluster


class TestReplicationHostFiltering:
    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_primary_skipped(self, mock_fetch, mock_client):
        # Primaries don't lag against themselves — section only checks secondaries.
        cluster = make_cluster()
        primary = make_host(replica_state_name="PRIMARY")
        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.hosts) == 0
        mock_fetch.assert_not_called()

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_secondary_gets_lag_check(self, mock_fetch, mock_client):
        mock_fetch.return_value = {
            "OPLOG_REPLICATION_LAG_TIME": (0.5, 0.3),
        }
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        assert len(section.hosts) == 1
        metric_names = {c.name for c in section.hosts[0].checks}
        assert metric_names == {"OPLOG_REPLICATION_LAG_TIME"}

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_arbiter_and_mongos_skipped(self, mock_fetch, mock_client):
        cluster = make_cluster()
        hosts = [
            make_host(replica_state_name="ARBITER", type_name="REPLICA_ARBITER"),
            make_host(replica_state_name=None, type_name="SHARD_MONGOS"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        assert len(section.hosts) == 0
        mock_fetch.assert_not_called()

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_only_secondaries_checked(self, mock_fetch, mock_client):
        mock_fetch.return_value = {"OPLOG_REPLICATION_LAG_TIME": (0.5, 0.3)}
        cluster = make_cluster()
        hosts = [
            make_host(host_id="h1", replica_state_name="PRIMARY"),
            make_host(host_id="h2", hostname="mongo2.example.com", replica_state_name="SECONDARY"),
            make_host(host_id="h3", hostname="mongo3.example.com", replica_state_name="SECONDARY"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        assert len(section.hosts) == 2


class TestReplicationStatus:
    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_lag_red(self, mock_fetch, mock_client):
        mock_fetch.return_value = {"OPLOG_REPLICATION_LAG_TIME": (15, 0)}  # > 10s
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        assert section.hosts[0].checks[0].status == STATUS_RED

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_lag_warn(self, mock_fetch, mock_client):
        mock_fetch.return_value = {"OPLOG_REPLICATION_LAG_TIME": (5, 0)}  # > 2 warn, < 10 red
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        assert section.hosts[0].checks[0].status == STATUS_WARN

    @patch("om_health_check.checks.replication.fetch_host_metrics")
    def test_lag_green(self, mock_fetch, mock_client):
        mock_fetch.return_value = {"OPLOG_REPLICATION_LAG_TIME": (1, 0)}  # < 2 warn
        cluster = make_cluster()
        secondary = make_host(replica_state_name="SECONDARY")
        section = run(mock_client, "p1", cluster, [secondary])
        assert section.hosts[0].checks[0].status == STATUS_GREEN
