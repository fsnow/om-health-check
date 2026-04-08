"""Tests for disk check module."""

from unittest.mock import patch, MagicMock

from om_health_check.checks.disk import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_INFO, STATUS_WARN
from tests.conftest import make_host, make_cluster, make_disk


class TestDiskMetrics:
    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_green_metrics(self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary):
        disk = make_disk("data")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (2.0, 2.5),
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (60, 65),
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0)}

        section = run(mock_client, "p1", cluster, [primary])
        checks = section.hosts[0].checks
        assert len(checks) == 6
        assert all(c.status == STATUS_GREEN for c in checks)

    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_red_latency(self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary):
        disk = make_disk("data")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (15.0, 3.0),  # > 10 and 5x > 3.0 = RED
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (60, 65),
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0)}

        section = run(mock_client, "p1", cluster, [primary])
        latency_check = [c for c in section.hosts[0].checks if "LATENCY_READ" in c.name][0]
        assert latency_check.status == STATUS_RED

    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_space_low_red(self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary):
        disk = make_disk("data")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (2.0, 2.5),
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (5, 60),  # <= 10 = RED
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0)}

        section = run(mock_client, "p1", cluster, [primary])
        space_check = [c for c in section.hosts[0].checks if "SPACE_PERCENT" in c.name][0]
        assert space_check.status == STATUS_RED

    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_partition_name_in_check_name(self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary):
        disk = make_disk("nvme1n1")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (2.0, 2.5),
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (60, 65),
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (1.0, 1.0)}

        section = run(mock_client, "p1", cluster, [primary])
        assert all("[nvme1n1]" in c.name for c in section.hosts[0].checks)

    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_no_disks_empty_section(self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary):
        mock_client.om.deployments.list_disks.return_value = []
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (None, None)}

        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.hosts[0].checks) == 0


class TestIowaitCorrelation:
    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_correlation_when_disk_red_and_iowait_elevated(
        self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary
    ):
        disk = make_disk("data")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (15.0, 3.0),  # RED
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (60, 65),
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        # iowait RED: 25% > 20 and 5x > 3.0
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (25.0, 5.0)}

        section = run(mock_client, "p1", cluster, [primary])
        correlation = [c for c in section.hosts[0].checks if "iowait" in c.name.lower()]
        assert len(correlation) == 1
        assert "correlates" in correlation[0].message

    @patch("om_health_check.checks.disk.fetch_host_metrics")
    @patch("om_health_check.checks.disk.fetch_disk_metrics")
    def test_no_correlation_when_disk_green(
        self, mock_disk_fetch, mock_host_fetch, mock_client, cluster, primary
    ):
        disk = make_disk("data")
        mock_client.om.deployments.list_disks.return_value = [disk]
        mock_disk_fetch.return_value = {
            "DISK_PARTITION_LATENCY_READ": (2.0, 2.5),
            "DISK_PARTITION_LATENCY_WRITE": (3.0, 3.0),
            "DISK_PARTITION_IOPS_READ": (100, 120),
            "DISK_PARTITION_IOPS_WRITE": (80, 90),
            "DISK_PARTITION_SPACE_PERCENT_FREE": (60, 65),
            "DISK_PARTITION_QUEUE_DEPTH": (1, 1),
        }
        mock_host_fetch.return_value = {"SYSTEM_NORMALIZED_CPU_IOWAIT": (25.0, 5.0)}

        section = run(mock_client, "p1", cluster, [primary])
        correlation = [c for c in section.hosts[0].checks if "iowait" in c.name.lower()]
        assert len(correlation) == 0
