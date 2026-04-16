"""Tests for runner permission error handling."""

from unittest.mock import patch, MagicMock

from opsmanager.errors import OpsManagerAuthenticationError, OpsManagerForbiddenError

from om_health_check.config import Config
from om_health_check.models import STATUS_RED
from om_health_check.runner import run, _PERMISSION_HINT


def _config(**kwargs):
    defaults = dict(
        om_url="https://om.example.com",
        username="user",
        api_key="key",
        project_names=["Prod"],
        cluster_name=None,
        formats=["txt"],
    )
    defaults.update(kwargs)
    return Config(**defaults)


class TestAuthErrors:
    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_auth_failure_on_connect(self, mock_render, mock_client_cls):
        mock_client_cls.side_effect = OpsManagerAuthenticationError("bad creds")
        report = run(_config())
        check = report.clusters[0].sections[0].cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Authentication failed" in check.message
        assert "OPS_MANAGER_USER" in check.message

    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_forbidden_on_connect(self, mock_render, mock_client_cls):
        mock_client_cls.side_effect = OpsManagerForbiddenError("no access")
        report = run(_config())
        check = report.clusters[0].sections[0].cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Access denied" in check.message
        assert "Project Read Only" in check.message


class TestProjectPermissionErrors:
    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_forbidden_on_project_resolution(self, mock_render, mock_client_cls):
        client = MagicMock()
        client.resolve_project.side_effect = OpsManagerForbiddenError("forbidden")
        mock_client_cls.return_value = client
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        report = run(_config())
        check = report.clusters[0].sections[0].cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Permission denied" in check.message
        assert "Project Read Only" in check.message

    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_auth_failure_on_project_resolution(self, mock_render, mock_client_cls):
        client = MagicMock()
        client.resolve_project.side_effect = OpsManagerAuthenticationError("expired")
        mock_client_cls.return_value = client
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        report = run(_config())
        check = report.clusters[0].sections[0].cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Permission denied" in check.message


class TestSectionPermissionErrors:
    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_forbidden_on_section_shows_hint(self, mock_render, mock_client_cls):
        client = MagicMock()
        project = MagicMock()
        project.id = "p1"
        project.name = "Prod"
        client.resolve_project.return_value = project
        cluster = MagicMock()
        cluster.id = "c1"
        cluster.cluster_name = "rs0"
        client.get_clusters.return_value = [cluster]
        host = MagicMock()
        host.host_port = "h1:27017"
        host.replica_state_name = "PRIMARY"
        host.type_name = "REPLICA_PRIMARY"
        host.is_primary = True
        host.is_secondary = False
        host.is_arbiter = False
        host.is_mongos = False
        client.get_hosts_for_cluster.return_value = [host]
        mock_client_cls.return_value = client
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        # Make every check section raise ForbiddenError
        with patch("om_health_check.runner.CHECK_SECTIONS", [
            ("Test Section", MagicMock(side_effect=OpsManagerForbiddenError("no access"))),
        ]):
            report = run(_config())

        section = report.clusters[0].sections[0]
        check = section.cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Permission denied" in check.message
        assert "Project Read Only" in check.message

    @patch("om_health_check.runner.HealthCheckClient")
    @patch("om_health_check.runner._render")
    def test_generic_error_still_works(self, mock_render, mock_client_cls):
        client = MagicMock()
        project = MagicMock()
        project.id = "p1"
        project.name = "Prod"
        client.resolve_project.return_value = project
        cluster = MagicMock()
        cluster.id = "c1"
        cluster.cluster_name = "rs0"
        client.get_clusters.return_value = [cluster]
        client.get_hosts_for_cluster.return_value = []
        mock_client_cls.return_value = client
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        with patch("om_health_check.runner.CHECK_SECTIONS", [
            ("Test Section", MagicMock(side_effect=RuntimeError("something broke"))),
        ]):
            report = run(_config())

        section = report.clusters[0].sections[0]
        check = section.cluster_checks[0]
        assert check.status == STATUS_RED
        assert "Check failed" in check.message
        assert "something broke" in check.message
