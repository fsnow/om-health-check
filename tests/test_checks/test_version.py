"""Tests for version check module."""

import om_health_check.checks.version as version_mod
from om_health_check.checks.version import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_INFO
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

    def test_mixed_versions_info(self, mock_client, cluster):
        """Mixed versions default to INFO (customer preference), not RED."""
        hosts = [
            make_host(host_id="h1", hostname="m1", version="7.0.38"),
            make_host(host_id="h2", hostname="m2", version="7.0.29"),
            make_host(host_id="h3", hostname="m3", version="7.0.38"),
        ]
        section = run(mock_client, "p1", cluster, hosts)
        consistency = [c for c in section.cluster_checks if c.name == "Version consistency"]
        assert consistency[0].status == STATUS_INFO
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

    def test_below_minimum_info(self, mock_client, cluster):
        """Below-minimum defaults to INFO; base message, no baked-in CVE text."""
        hosts = [make_host(version="7.0.36", hostname="m1")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_INFO
        assert "below minimum safe version 7.0.37" in bad_checks[0].message
        assert "Affected hosts:" in bad_checks[0].message
        # No advisory text is hardcoded — that lives only in the YAML config.
        assert "CVE" not in bad_checks[0].message

    def test_below_minimum_note_appended(self, mock_client, cluster):
        """A configured version_note is appended to the below-minimum message."""
        original = dict(version_mod.VERSION_NOTES)
        try:
            version_mod.VERSION_NOTES["7.0"] = "addresses CVE-2026-11933"
            hosts = [make_host(version="7.0.36")]
            section = run(mock_client, "p1", cluster, hosts)
            bad = [c for c in section.cluster_checks if c.name == "Version check"]
            assert "— addresses CVE-2026-11933. Affected hosts:" in bad[0].message
        finally:
            version_mod.VERSION_NOTES.clear()
            version_mod.VERSION_NOTES.update(original)

    def test_version_8_0_safe(self, mock_client, cluster):
        hosts = [make_host(version="8.0.26")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_version_8_0_below_info(self, mock_client, cluster):
        hosts = [make_host(version="8.0.25")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_INFO

    def test_version_8_3_safe(self, mock_client, cluster):
        hosts = [make_host(version="8.3.4")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_GREEN

    def test_version_8_3_below_info(self, mock_client, cluster):
        hosts = [make_host(version="8.3.3")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert bad_checks[0].status == STATUS_INFO

    def test_version_9_0_recognized_green(self, mock_client, cluster):
        """9.0 line is recognized (not 'no data') and passes the 9.0.0 floor."""
        hosts = [make_host(version="9.0.2")]
        section = run(mock_client, "p1", cluster, hosts)
        bad_checks = [c for c in section.cluster_checks if c.name == "Version check"]
        assert len(bad_checks) == 1
        assert bad_checks[0].status == STATUS_GREEN

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


class TestSeverityOverride:
    def test_severity_override_to_red(self, mock_client, cluster):
        """version.severity=red flips below-minimum + mixed findings to RED."""
        original = version_mod.VERSION_SEVERITY
        try:
            version_mod.VERSION_SEVERITY = STATUS_RED
            hosts = [make_host(version="7.0.36")]
            section = run(mock_client, "p1", cluster, hosts)
            bad = [c for c in section.cluster_checks if c.name == "Version check"]
            assert bad[0].status == STATUS_RED
        finally:
            version_mod.VERSION_SEVERITY = original

    def test_load_version_overrides_from_yaml(self, tmp_path, mock_client, cluster):
        """A config file's version block sets severity and merges minimums."""
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "version:\n"
            "  severity: red\n"
            "  minimum_safe_versions:\n"
            '    "7.0": "7.0.99"\n'
        )
        original_sev = version_mod.VERSION_SEVERITY
        original_min = dict(version_mod.MINIMUM_SAFE_VERSIONS)
        try:
            version_mod.load_version_overrides(str(cfg))
            assert version_mod.VERSION_SEVERITY == STATUS_RED
            assert version_mod.MINIMUM_SAFE_VERSIONS["7.0"] == "7.0.99"
            # unlisted lines keep their defaults (merge, not replace)
            assert version_mod.MINIMUM_SAFE_VERSIONS["8.0"] == original_min["8.0"]
            # 7.0.38 is now below the overridden 7.0.99 floor → RED finding
            section = run(mock_client, "p1", cluster, [make_host(version="7.0.38")])
            bad = [c for c in section.cluster_checks if c.name == "Version check"]
            assert bad[0].status == STATUS_RED
        finally:
            version_mod.VERSION_SEVERITY = original_sev
            version_mod.MINIMUM_SAFE_VERSIONS.clear()
            version_mod.MINIMUM_SAFE_VERSIONS.update(original_min)
