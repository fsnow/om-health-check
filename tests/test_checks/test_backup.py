"""Tests for backup check module."""

from unittest.mock import MagicMock

from om_health_check.checks.backup import run
from om_health_check.models import STATUS_GREEN, STATUS_RED, STATUS_INFO, STATUS_WARN
from tests.conftest import make_cluster, make_host


def _make_backup_config(status="STARTED"):
    config = MagicMock()
    config.status_name = status
    return config


def _make_schedule(interval_hours=6):
    schedule = MagicMock()
    schedule.snapshot_interval_hours = interval_hours
    return schedule


def _make_snapshot(complete=True, hours_ago=2):
    from datetime import datetime, timedelta, timezone
    snap = MagicMock()
    snap.complete = complete
    created_dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    snap.created = {"date": created_dt.isoformat()}
    snap.parts = []
    return snap


class TestBackupNotConfigured:
    def test_backup_exception_info(self, mock_client, cluster, primary):
        section = run(mock_client, "p1", cluster, [primary])
        assert section.cluster_checks[0].status == STATUS_INFO
        assert "not available" in section.cluster_checks[0].message

    def test_backup_inactive_info(self, mock_client, cluster, primary):
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config("INACTIVE")
        section = run(mock_client, "p1", cluster, [primary])
        assert section.cluster_checks[0].status == STATUS_INFO
        assert "INACTIVE" in section.cluster_checks[0].message


class TestBackupCaptureLag:
    def test_recent_snapshot_green(self, mock_client, cluster, primary):
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config()
        mock_client.om.backup.get_snapshot_schedule.return_value = _make_schedule(6)
        mock_client.om.backup.list_snapshots.return_value = [_make_snapshot(hours_ago=2)]
        section = run(mock_client, "p1", cluster, [primary])
        lag_checks = [c for c in section.cluster_checks if c.name == "Backup capture lag"]
        assert lag_checks[0].status == STATUS_GREEN

    def test_overdue_snapshot_red(self, mock_client, cluster, primary):
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config()
        mock_client.om.backup.get_snapshot_schedule.return_value = _make_schedule(6)
        # 10 hours ago > 6 * 1.5 = 9 hours threshold
        mock_client.om.backup.list_snapshots.return_value = [_make_snapshot(hours_ago=10)]
        section = run(mock_client, "p1", cluster, [primary])
        lag_checks = [c for c in section.cluster_checks if c.name == "Backup capture lag"]
        assert lag_checks[0].status == STATUS_RED
        assert "delayed" in lag_checks[0].message

    def test_no_snapshots_red(self, mock_client, cluster, primary):
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config()
        mock_client.om.backup.get_snapshot_schedule.return_value = _make_schedule(6)
        mock_client.om.backup.list_snapshots.return_value = []
        section = run(mock_client, "p1", cluster, [primary])
        lag_checks = [c for c in section.cluster_checks if c.name == "Backup capture lag"]
        assert lag_checks[0].status == STATUS_RED
        assert "No snapshots" in lag_checks[0].message

    def test_in_progress_snapshot_warn(self, mock_client, cluster, primary):
        """A backup running during the check is WARN (customer request)."""
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config()
        mock_client.om.backup.get_snapshot_schedule.return_value = _make_schedule(6)
        mock_client.om.backup.list_snapshots.return_value = [_make_snapshot(complete=False, hours_ago=0)]
        section = run(mock_client, "p1", cluster, [primary])
        progress_checks = [c for c in section.cluster_checks if c.name == "Snapshot in progress"]
        assert len(progress_checks) == 1
        assert progress_checks[0].status == STATUS_WARN

    def test_snapshot_data_unavailable_suppressed(self, mock_client, cluster, primary):
        """When snapshot data can't be retrieved, emit no 'could not retrieve'
        line — only the GREEN 'Backup is enabled and active' remains."""
        mock_client.om.backup.get_backup_config.side_effect = None
        mock_client.om.backup.get_backup_config.return_value = _make_backup_config()
        mock_client.om.backup.get_snapshot_schedule.side_effect = Exception("404 snapshotSchedule")
        section = run(mock_client, "p1", cluster, [primary])
        assert len(section.cluster_checks) == 1
        assert section.cluster_checks[0].status == STATUS_GREEN
        assert "enabled and active" in section.cluster_checks[0].message
        assert not any("could not retrieve" in c.message.lower() for c in section.cluster_checks)
