"""Tests for workload check module."""

from unittest.mock import patch, MagicMock

from om_health_check.checks.workload import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_INFO


def _green_metrics():
    """All workload metrics at healthy levels."""
    return {
        "QUERY_TARGETING_SCANNED_PER_RETURNED": (50, 45),
        "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED": (30, 28),
        "QUERY_EXECUTOR_SCANNED": (1000, 900),
        "QUERY_EXECUTOR_SCANNED_OBJECTS": (800, 750),
        "DOCUMENT_METRICS_RETURNED": (500, 480),
        "DOCUMENT_METRICS_INSERTED": (100, 90),
        "DOCUMENT_METRICS_UPDATED": (200, 190),
        "DOCUMENT_METRICS_DELETED": (10, 8),
        "OPERATIONS_SCAN_AND_ORDER": (5, 4),
        "OPCOUNTER_CMD": (300, 280),
        "OPCOUNTER_QUERY": (1000, 900),
        "OPCOUNTER_UPDATE": (200, 190),
        "OPCOUNTER_DELETE": (10, 8),
        "OPCOUNTER_GETMORE": (50, 45),
        "OPCOUNTER_INSERT": (100, 90),
        "OP_EXECUTION_TIME_READS": (20, 18),
        "OP_EXECUTION_TIME_WRITES": (15, 12),
        "OP_EXECUTION_TIME_COMMANDS": (10, 8),
        "GLOBAL_LOCK_CURRENT_QUEUE_READERS": (0, 0),
        "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS": (0, 0),
        "GLOBAL_LOCK_CURRENT_QUEUE_TOTAL": (0, 0),
    }


class TestWorkloadMetrics:
    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_all_green(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        assert all(c.status == STATUS_GREEN for c in checks)

    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_query_targeting_red(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        metrics = _green_metrics()
        metrics["QUERY_TARGETING_SCANNED_PER_RETURNED"] = (1500, 500)  # > 1000 and 3x > 2.0
        mock_fetch.return_value = metrics

        section = run(mock_client, "p1", cluster, [primary])
        targeting = [c for c in section.hosts[0].checks if c.name == "QUERY_TARGETING_SCANNED_PER_RETURNED"][0]
        assert targeting.status == STATUS_RED

    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_execution_time_red(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        metrics = _green_metrics()
        metrics["OP_EXECUTION_TIME_READS"] = (120, 50)  # > 100 threshold
        mock_fetch.return_value = metrics

        section = run(mock_client, "p1", cluster, [primary])
        exec_check = [c for c in section.hosts[0].checks if c.name == "OP_EXECUTION_TIME_READS"][0]
        assert exec_check.status == STATUS_RED

    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_global_lock_queue_red(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        metrics = _green_metrics()
        metrics["GLOBAL_LOCK_CURRENT_QUEUE_TOTAL"] = (25, 5)  # > 20 and 5x > 3.0
        mock_fetch.return_value = metrics

        section = run(mock_client, "p1", cluster, [primary])
        queue_check = [c for c in section.hosts[0].checks if c.name == "GLOBAL_LOCK_CURRENT_QUEUE_TOTAL"][0]
        assert queue_check.status == STATUS_RED

    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_opcounter_spike_red(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        metrics = _green_metrics()
        metrics["OPCOUNTER_QUERY"] = (10000, 2000)  # 5x > 3.0 (baseline mode)
        mock_fetch.return_value = metrics

        section = run(mock_client, "p1", cluster, [primary])
        opcnt = [c for c in section.hosts[0].checks if c.name == "OPCOUNTER_QUERY"][0]
        assert opcnt.status == STATUS_RED

    @patch("om_health_check.checks.workload._check_performance_advisor")
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_units_correct(self, mock_fetch, mock_advisor, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        section = run(mock_client, "p1", cluster, [primary])
        checks = {c.name: c for c in section.hosts[0].checks}
        assert checks["QUERY_TARGETING_SCANNED_PER_RETURNED"].units == "ratio"
        assert checks["OP_EXECUTION_TIME_READS"].units == "ms"
        assert checks["OPCOUNTER_QUERY"].units == "ops/s"


class TestPerformanceAdvisor:
    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_suggested_indexes_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        mock_client.om.performance_advisor.get_slow_queries.return_value = []
        idx = MagicMock()
        idx.namespace = "db.collection"
        mock_client.om.performance_advisor.get_suggested_indexes.return_value = {
            "suggested_indexes": [idx],
            "shapes": [],
        }

        section = run(mock_client, "p1", cluster, [primary])
        advisor = [c for c in section.hosts[0].checks if "suggested indexes" in c.name.lower()]
        assert len(advisor) == 1
        assert advisor[0].status == STATUS_RED
        assert "db.collection" in advisor[0].message

    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_slow_queries_red(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        mock_client.om.performance_advisor.get_slow_queries.return_value = [MagicMock()]
        mock_client.om.performance_advisor.get_suggested_indexes.return_value = {
            "suggested_indexes": [],
            "shapes": [],
        }

        section = run(mock_client, "p1", cluster, [primary])
        advisor = [c for c in section.hosts[0].checks if "slow queries" in c.name.lower()]
        assert len(advisor) == 1
        assert advisor[0].status == STATUS_RED

    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_no_issues_green(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        mock_client.om.performance_advisor.get_slow_queries.return_value = []
        mock_client.om.performance_advisor.get_suggested_indexes.return_value = {
            "suggested_indexes": [],
            "shapes": [],
        }

        section = run(mock_client, "p1", cluster, [primary])
        advisor = [c for c in section.hosts[0].checks if "performance advisor" in c.name.lower()]
        assert len(advisor) == 1
        assert advisor[0].status == STATUS_GREEN

    @patch("om_health_check.checks.workload.fetch_host_metrics")
    def test_advisor_unavailable_info(self, mock_fetch, mock_client, cluster, primary):
        mock_fetch.return_value = _green_metrics()
        mock_client.om.performance_advisor.get_slow_queries.side_effect = Exception("unavailable")

        section = run(mock_client, "p1", cluster, [primary])
        advisor = [c for c in section.hosts[0].checks if "performance advisor" in c.name.lower()]
        assert len(advisor) == 1
        assert advisor[0].status == STATUS_INFO
        assert "unavailable" in advisor[0].message.lower()
