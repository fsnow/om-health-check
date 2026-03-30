"""Section 8: Backup checks."""

from __future__ import annotations

from datetime import datetime, timezone

from opsmanager.types import Cluster, Host

from om_health_check.client import HealthCheckClient
from om_health_check.models import STATUS_GREEN, STATUS_INFO, STATUS_RED, Check, Section


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Backup")

    # Check if backup is enabled
    try:
        config = client.om.backup.get_backup_config(project_id, cluster.id)
    except Exception:
        section.cluster_checks.append(
            Check(
                name="Backup configuration",
                status=STATUS_INFO,
                message="Backup configuration not available for this cluster",
            )
        )
        return section

    if config.status_name != "STARTED":
        section.cluster_checks.append(
            Check(
                name="Backup configuration",
                status=STATUS_INFO,
                message=f"Backup status: {config.status_name}",
            )
        )
        return section

    section.cluster_checks.append(
        Check(
            name="Backup configuration",
            status=STATUS_GREEN,
            message="Backup is enabled and active",
        )
    )

    # Check snapshot schedule and latest snapshot
    try:
        schedule = client.om.backup.get_snapshot_schedule(project_id, cluster.id)
        snapshots = client.om.backup.list_snapshots(project_id, cluster.id)
    except Exception as exc:
        section.cluster_checks.append(
            Check(
                name="Backup capture lag",
                status=STATUS_INFO,
                message=f"Could not retrieve snapshot data: {exc}",
            )
        )
        return section

    if not snapshots:
        section.cluster_checks.append(
            Check(
                name="Backup capture lag",
                status=STATUS_RED,
                message="No snapshots found — backup may not be capturing",
            )
        )
        return section

    latest = snapshots[0]

    # Check for in-progress snapshots
    if not latest.complete:
        section.cluster_checks.append(
            Check(
                name="Snapshot in progress",
                status=STATUS_INFO,
                message="A snapshot is currently being captured",
            )
        )
        # Note which replica set members are involved
        if latest.parts:
            for part in latest.parts:
                if part.replica_state:
                    section.cluster_checks.append(
                        Check(
                            name="Snapshot source",
                            status=STATUS_INFO,
                            message=(
                                f"Replica set {part.replica_set_name}: "
                                f"snapshot from {part.replica_state}"
                            ),
                        )
                    )

    # Check if latest snapshot is overdue
    if latest.created and isinstance(latest.created, dict):
        created_str = latest.created.get("date", "")
        if created_str:
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                hours_since = (now - created_dt).total_seconds() / 3600

                expected_interval = schedule.snapshot_interval_hours
                # Allow 50% grace period before flagging as overdue
                overdue_threshold = expected_interval * 1.5

                if hours_since > overdue_threshold:
                    section.cluster_checks.append(
                        Check(
                            name="Backup capture lag",
                            status=STATUS_RED,
                            value=round(hours_since, 1),
                            units="hours",
                            message=(
                                f"Latest snapshot is {hours_since:.1f}h old "
                                f"(expected every {expected_interval}h) — "
                                "snapshot may be delayed"
                            ),
                        )
                    )
                else:
                    section.cluster_checks.append(
                        Check(
                            name="Backup capture lag",
                            status=STATUS_GREEN,
                            value=round(hours_since, 1),
                            units="hours",
                            message=(
                                f"Latest snapshot is {hours_since:.1f}h old "
                                f"(expected every {expected_interval}h)"
                            ),
                        )
                    )
            except (ValueError, TypeError):
                section.cluster_checks.append(
                    Check(
                        name="Backup capture lag",
                        status=STATUS_INFO,
                        message=f"Could not parse snapshot timestamp: {created_str}",
                    )
                )

    return section
