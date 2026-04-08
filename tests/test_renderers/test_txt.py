"""Tests for text renderer."""

from om_health_check.models import Report, STATUS_GREEN
from om_health_check.renderers.txt import render
from tests.conftest import make_sample_report


class TestTxtRenderer:
    def test_contains_header(self):
        output = render(make_sample_report())
        assert "OM HEALTH CHECK REPORT" in output

    def test_contains_om_url(self):
        output = render(make_sample_report())
        assert "https://om.example.com" in output

    def test_contains_cluster_name(self):
        output = render(make_sample_report())
        assert "rs0" in output

    def test_contains_project_name(self):
        output = render(make_sample_report())
        assert "Prod" in output

    def test_overall_status_shown(self):
        output = render(make_sample_report())
        assert "[RED]" in output

    def test_section_headers(self):
        output = render(make_sample_report())
        assert "## Connectivity & Infrastructure" in output
        assert "## Cache Resources" in output

    def test_host_shown(self):
        output = render(make_sample_report())
        assert "mongo1:27017 (PRIMARY)" in output

    def test_status_tags(self):
        output = render(make_sample_report())
        assert "[GREEN]" in output
        assert "[RED]" in output
        assert "[WARN]" in output

    def test_check_messages(self):
        output = render(make_sample_report())
        assert "Connected" in output
        assert "HOST_DOWN" in output
        assert "approaching" in output

    def test_summary_line(self):
        output = render(make_sample_report())
        assert "Summary:" in output
        assert "2 RED" in output
        assert "1 WARN" in output
        assert "2 GREEN" in output

    def test_empty_report(self):
        r = Report(om_url="https://om.example.com")
        output = render(r)
        assert "OM HEALTH CHECK REPORT" in output
        assert "[GREEN]" in output  # overall status
