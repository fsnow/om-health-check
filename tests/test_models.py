"""Tests for the models module — specifically the status rollup rules."""

from om_health_check.models import (
    STATUS_GREEN,
    STATUS_INFO,
    STATUS_RED,
    STATUS_WARN,
    Check,
    ClusterReport,
    HostSection,
    Report,
    Section,
    worst_status,
)


class TestWorstStatus:
    def test_red_wins(self):
        assert worst_status(STATUS_GREEN, STATUS_WARN, STATUS_RED) == STATUS_RED

    def test_warn_beats_info(self):
        assert worst_status(STATUS_INFO, STATUS_WARN) == STATUS_WARN

    def test_info_beats_green(self):
        assert worst_status(STATUS_GREEN, STATUS_INFO) == STATUS_INFO


class TestInfoDoesNotBubble:
    """INFO is informational and must not bubble up to section/cluster/overall."""

    def test_host_section_with_only_info_is_green(self):
        hs = HostSection(host="h1:27017", role="PRIMARY")
        hs.checks.append(Check(name="c1", status=STATUS_INFO, message="advisory"))
        hs.checks.append(Check(name="c2", status=STATUS_GREEN, message="ok"))
        assert hs.status == STATUS_GREEN

    def test_host_section_with_warn_is_warn(self):
        hs = HostSection(host="h1:27017", role="PRIMARY")
        hs.checks.append(Check(name="c1", status=STATUS_INFO, message="advisory"))
        hs.checks.append(Check(name="c2", status=STATUS_WARN, message="warn"))
        assert hs.status == STATUS_WARN

    def test_section_cluster_checks_info_does_not_bubble(self):
        s = Section(name="Test")
        s.cluster_checks.append(Check(name="advisory", status=STATUS_INFO))
        assert s.status == STATUS_GREEN

    def test_overall_status_green_with_only_info_alerts(self):
        """The key customer requirement: INFO advisory alerts shouldn't make overall non-GREEN."""
        r = Report(om_url="https://om.example.com")
        cr = ClusterReport(
            cluster_name="rs0", cluster_id="c1",
            project_name="Prod", project_id="p1",
        )
        s = Section(name="Connectivity")
        s.cluster_checks.append(
            Check(name="Active alert", status=STATUS_INFO, message="HOST_SECURITY_CHECKUP_NOT_MET")
        )
        cr.sections.append(s)
        r.clusters.append(cr)
        assert r.overall_status == STATUS_GREEN


class TestRollupOptOut:
    """Individual WARN/RED checks can opt out of rollup via rollup=False."""

    def test_rollup_false_excludes_warn(self):
        hs = HostSection(host="h1:27017", role="PRIMARY")
        hs.checks.append(Check(name="suppressed", status=STATUS_WARN, rollup=False))
        hs.checks.append(Check(name="normal", status=STATUS_GREEN))
        assert hs.status == STATUS_GREEN

    def test_rollup_false_excludes_red(self):
        hs = HostSection(host="h1:27017", role="PRIMARY")
        hs.checks.append(Check(name="suppressed", status=STATUS_RED, rollup=False))
        assert hs.status == STATUS_GREEN
