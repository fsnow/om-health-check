"""Tests for JSON renderer."""

import json

from om_health_check.models import Report
from om_health_check.renderers.json_renderer import render
from tests.conftest import make_sample_report


class TestJsonRenderer:
    def test_valid_json(self):
        output = render(make_sample_report())
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_overall_status(self):
        parsed = json.loads(render(make_sample_report()))
        assert parsed["overall_status"] == "RED"

    def test_cluster_structure(self):
        parsed = json.loads(render(make_sample_report()))
        clusters = parsed["clusters"]
        assert len(clusters) == 1
        assert clusters[0]["cluster_name"] == "rs0"
        assert clusters[0]["project_name"] == "Prod"
        assert clusters[0]["overall_status"] == "RED"

    def test_section_structure(self):
        parsed = json.loads(render(make_sample_report()))
        sections = parsed["clusters"][0]["sections"]
        assert len(sections) == 3
        assert sections[0]["name"] == "Connectivity & Infrastructure"
        assert sections[0]["status"] == "RED"

    def test_host_check_fields(self):
        parsed = json.loads(render(make_sample_report()))
        check = parsed["clusters"][0]["sections"][2]["hosts"][0]["checks"][0]
        assert check["name"] == "CONNECTIONS"
        assert check["status"] == "RED"
        assert check["value"] == 26000
        assert check["threshold"] == 25000
        assert check["baseline_value"] == 10000
        assert check["baseline_deviation"] == 2.6

    def test_cluster_checks(self):
        parsed = json.loads(render(make_sample_report()))
        cluster_checks = parsed["clusters"][0]["sections"][0]["cluster_checks"]
        assert len(cluster_checks) == 2
        statuses = {c["status"] for c in cluster_checks}
        assert "GREEN" in statuses
        assert "RED" in statuses

    def test_om_url(self):
        parsed = json.loads(render(make_sample_report()))
        assert parsed["om_url"] == "https://om.example.com"

    def test_timing_fields(self):
        parsed = json.loads(render(make_sample_report()))
        assert "started_at" in parsed
        assert len(parsed["started_at"]) > 0
        assert "finished_at" in parsed
        assert "elapsed_seconds" in parsed

    def test_warn_status_present(self):
        parsed = json.loads(render(make_sample_report()))
        cache_section = parsed["clusters"][0]["sections"][1]
        check = cache_section["hosts"][0]["checks"][0]
        assert check["status"] == "WARN"

    def test_empty_report(self):
        r = Report(om_url="https://om.example.com")
        parsed = json.loads(render(r))
        assert parsed["overall_status"] == "GREEN"
        assert parsed["clusters"] == []
