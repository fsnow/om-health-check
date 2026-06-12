"""Tests for version check module."""

from om_health_check.checks.version import run
from om_health_check.models import STATUS_GREEN, STATUS_RED
from tests.conftest import make_host, make_cluster


class TestVersionConsistency:
    def test_all_same_green(self, mock_client, cluster):
        hosts = [
            make_host(host_id="h1", hostname="m1", version="7.0.38"),
            make_host(host_id="h2", hostname="m2", version="7.0.38"),
            make_host(host_id="h3", hostname="m3", version="7.0.38"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        consistency = [c for c in section.cluster_checks if c.name == "Version consistency"]
        assert consistency[0].status == STATUS_GREEN
        assert "All 3" in consistency[0].message

    def test_mixed_versions_red(self, mock_client, cluster):
        hosts = [
            make_host(host_id="h1", hostname="m1", version="7.0.38"),
            make_host(host_id="h2", hostname="m2", version="7.0.29"),
            make_host(host_id="h3", hostname="m3", version="7.0.38"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        consistency = [c for c in section.cluster_checks if c.name == "Version consistency"]
        assert consistency[0].status == STATUS_RED
        assert "Inconsistent" in consistency[0].message


class TestKnownBadVersions:
    def test_safe_version_green(self, mock_client, cluster):
        hosts = [make_host(version="7.0.38")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_exact_minimum_green(self, mock_client, cluster):
        hosts = [make_host(version="7.0.37")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_below_minimum_red(self, mock_client, cluster):
        hosts = [make_host(version="7.0.36")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_RED
        assert "CVE" in bad_checks[0].message

    def test_version_8_0_safe(self, mock_client, cluster):
        hosts = [make_host(version="8.0.26")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_version_8_0_bad(self, mock_client, cluster):
        hosts = [make_host(version="8.0.25")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_RED

    def test_version_8_3_safe(self, mock_client, cluster):
        hosts = [make_host(version="8.3.4")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_version_8_3_bad(self, mock_client, cluster):
        hosts = [make_host(version="8.3.3")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_RED

    def test_unknown_version_no_check(self, mock_client, cluster):
        hosts = [make_host(version="unknown")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert len(bad_checks) == 0

    def test_unmapped_major_minor_no_check(self, mock_client, cluster):
        hosts = [make_host(version="6.0.15")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert len(bad_checks) == 0
