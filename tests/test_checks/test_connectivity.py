"""Tests for connectivity check module."""

from unittest.mock import patch

from om_health_check.checks.connectivity import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_WARN, STATUS_INFO
from tests.conftest import make_agent, make_alert


_MOCK_METRICS = {k: (None, None) for k in [
    "SYSTEM_NETWORK_IN", "SYSTEM_NETWORK_OUT",
    "NETWORK_BYTES_IN", "NETWORK_BYTES_OUT", "NETWORK_NUM_REQUESTS",
]}


class TestOMReachability:
    def test_always_green(self, mock_client, cluster, primary):
        section = run(mock_client, "p1", cluster, [primary])
        api_check = section.cluster_checks[0]
        assert api_check.name == "OM API reachability"
        assert api_check.status == STATUS_GREEN


class TestActiveAlerts:
    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_no_alerts_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        section = run(mock_client, "p1", cluster, [primary])
        alert_checks = [c for c in section.cluster_checks if "alert" in c.name.lower()]
        assert len(alert_checks) == 1
        assert alert_checks[0].status == STATUS_GREEN

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_advisory_alert_is_info(self, mock_fetch, mock_client, cluster, primary):
        """HOST_SECURITY_CHECKUP_NOT_MET is advisory — should be INFO, not RED."""
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.alerts.list_open.return_value = [
            make_alert(
                hostname_and_port="mongo1.example.com:27017",
                event_type="HOST_SECURITY_CHECKUP_NOT_MET",
            ),
        ]
        section = run(mock_client, "p1", cluster, [primary])
        alert_checks = [c for c in section.cluster_checks if c.name == "Active alert"]
        assert len(alert_checks) == 1
        assert alert_checks[0].status == STATUS_INFO

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_matching_alert_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.alerts.list_open.return_value = [
            make_alert(hostname_and_port="mongo1.example.com:27017"),
        ]
        section = run(mock_client, "p1", cluster, [primary])
        alert_checks = [c for c in section.cluster_checks if c.name == "Active alert"]
        assert len(alert_checks) == 1
        assert alert_checks[0].status == STATUS_RED

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_unrelated_alert_not_shown(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.alerts.list_open.return_value = [
            make_alert(hostname_and_port="other-host:27017", cluster_name="other-cluster"),
        ]
        section = run(mock_client, "p1", cluster, [primary])
        alert_checks = [c for c in section.cluster_checks if "alert" in c.name.lower()]
        assert len(alert_checks) == 1
        assert alert_checks[0].status == STATUS_GREEN


class TestAgentStatus:
    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_active_agent_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.agents.list_monitoring.return_value = [
            make_agent(hostname="mongo1.example.com", state_name="ACTIVE"),
        ]
        section = run(mock_client, "p1", cluster, [primary])
        agent_checks = [c for c in section.cluster_checks if c.name == "Agent status"]
        assert any(c.status == STATUS_GREEN for c in agent_checks)

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_all_standby_warn(self, mock_fetch, mock_client, cluster, primary):
        """No ACTIVE agent is a monitoring gap (WARN), not a MongoDB fault."""
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.agents.list_monitoring.return_value = [
            make_agent(hostname="mongo1.example.com", state_name="STANDBY", last_ping="2026-04-01T00:00:00Z"),
        ]
        section = run(mock_client, "p1", cluster, [primary])
        agent_checks = [c for c in section.cluster_checks if c.name == "Agent status"]
        assert len(agent_checks) == 1
        assert agent_checks[0].status == STATUS_WARN
        assert "No ACTIVE" in agent_checks[0].message

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_one_active_others_standby_green(self, mock_fetch, mock_client, cluster, three_hosts):
        """OM leader election: one ACTIVE + rest STANDBY is expected healthy state."""
        mock_fetch.return_value = _MOCK_METRICS
        mock_client.om.agents.list_monitoring.return_value = [
            make_agent(hostname="mongo1.example.com", state_name="ACTIVE"),
            make_agent(hostname="mongo2.example.com", state_name="STANDBY"),
            make_agent(hostname="mongo3.example.com", state_name="STANDBY"),
        ]
        section = run(mock_client, "p1", cluster, three_hosts)
        agent_checks = [c for c in section.cluster_checks if c.name == "Agent status"]
        assert len(agent_checks) == 1
        assert agent_checks[0].status == STATUS_GREEN
        assert "2 standby" in agent_checks[0].message

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_no_agents_warn(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        section = run(mock_client, "p1", cluster, [primary])
        agent_checks = [c for c in section.cluster_checks if c.name == "Agent status"]
        assert agent_checks[0].status == STATUS_WARN
        assert "No monitoring agents" in agent_checks[0].message


class TestNodeStatus:
    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_healthy_node_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _MOCK_METRICS
        section = run(mock_client, "p1", cluster, [primary])
        node_checks = [c for hs in section.hosts for c in hs.checks if c.name == "Node status"]
        assert node_checks[0].status == STATUS_GREEN

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_disabled_node_info(self, mock_fetch, mock_client, cluster):
        """A disabled host is an admin action, not a fault — INFO, not RED."""
        from tests.conftest import make_host
        host = make_host(host_enabled=False)
        mock_fetch.return_value = _MOCK_METRICS
        section = run(mock_client, "p1", cluster, [host])
        node_checks = [c for hs in section.hosts for c in hs.checks if c.name == "Node status"]
        assert node_checks[0].status == STATUS_INFO
        assert "disabled" in node_checks[0].message.lower()

    @patch("om_health_check.checks.connectivity.fetch_host_metrics")
    def test_down_node_red(self, mock_fetch, mock_client, cluster):
        from tests.conftest import make_host
        host = make_host(replica_state_name="DOWN")
        mock_fetch.return_value = _MOCK_METRICS
        section = run(mock_client, "p1", cluster, [host])
        node_checks = [c for hs in section.hosts for c in hs.checks if c.name == "Node status"]
        assert node_checks[0].status == STATUS_RED
