"""Tests for HTML renderer."""

from om_health_check.models import Report, Section, HostSection, Check, ClusterReport, STATUS_GREEN, STATUS_RED
from om_health_check.renderers.html import render
from tests.conftest import make_sample_report


class TestHtmlRenderer:
    def test_valid_html(self):
        output = render(make_sample_report())
        assert output.startswith("<!DOCTYPE html>")
        assert "</html>" in output

    def test_contains_title(self):
        output = render(make_sample_report())
        assert "<title>OM Health Check Report</title>" in output

    def test_contains_om_url(self):
        output = render(make_sample_report())
        assert "https://om.example.com" in output

    def test_contains_cluster_name(self):
        output = render(make_sample_report())
        assert "rs0" in output

    def test_contains_section_names(self):
        output = render(make_sample_report())
        assert "Connectivity &amp;" in output  # autoescape
        assert "Cache Resources" in output

    def test_status_badges(self):
        output = render(make_sample_report())
        assert 'class="badge RED"' in output
        assert 'class="badge GREEN"' in output
        assert 'class="badge WARN"' in output

    def test_status_pills(self):
        output = render(make_sample_report())
        assert 'class="status-pill RED"' in output

    def test_host_shown(self):
        output = render(make_sample_report())
        assert "mongo1:27017" in output
        assert "PRIMARY" in output

    def test_check_messages(self):
        output = render(make_sample_report())
        assert "Connected" in output
        assert "exceeds threshold" in output

    def test_red_section_open_by_default(self):
        output = render(make_sample_report())
        assert "<details open>" in output

    def test_green_section_not_open(self):
        r = Report(om_url="https://om.example.com")
        cr = ClusterReport(cluster_name="rs0", cluster_id="c1", project_name="Prod", project_id="p1")
        s = Section(name="Test")
        hs = HostSection(host="h1:27017", role="PRIMARY")
        hs.checks.append(Check(name="check", status=STATUS_GREEN, message="ok"))
        s.hosts.append(hs)
        cr.sections.append(s)
        r.clusters.append(cr)
        output = render(r)
        # GREEN section should not have 'open' attribute
        assert "<details open>" not in output
        assert "<details>" in output

    def test_self_contained_css(self):
        output = render(make_sample_report())
        assert "<style>" in output
        assert "font-family" in output

    def test_no_external_dependencies(self):
        output = render(make_sample_report())
        assert '<link rel="stylesheet"' not in output
        assert "<script src=" not in output

    def test_empty_report(self):
        r = Report(om_url="https://om.example.com")
        output = render(r)
        assert "<!DOCTYPE html>" in output
        assert "GREEN" in output

    def test_html_escaping(self):
        """Verify autoescape prevents XSS in dynamic content."""
        r = Report(om_url="https://om.example.com")
        cr = ClusterReport(
            cluster_name='<script>alert("xss")</script>',
            cluster_id="c1", project_name="Prod", project_id="p1",
        )
        s = Section(name="Test")
        cr.sections.append(s)
        r.clusters.append(cr)
        output = render(r)
        assert "<script>alert" not in output
        assert "&lt;script&gt;" in output
