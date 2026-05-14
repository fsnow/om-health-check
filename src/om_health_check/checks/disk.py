"""Section 3: Disk Resources checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_disk_metrics, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
from om_health_check.models import STATUS_RED, STATUS_WARN, Check, HostSection, Section

_DISK_METRICS = [
    "DISK_PARTITION_LATENCY_READ",
    "DISK_PARTITION_LATENCY_WRITE",
    "DISK_PARTITION_IOPS_READ",
    "DISK_PARTITION_IOPS_WRITE",
    "DISK_PARTITION_SPACE_PERCENT_FREE",
]

_UNITS = {
    "DISK_PARTITION_LATENCY_READ": "ms",
    "DISK_PARTITION_LATENCY_WRITE": "ms",
    "DISK_PARTITION_IOPS_READ": "IOPS",
    "DISK_PARTITION_IOPS_WRITE": "IOPS",
    "DISK_PARTITION_SPACE_PERCENT_FREE": "%",
}


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Disk Resources")
    # Mongos has no data partition / disk metrics; skip those hosts.
    mongod_hosts = [h for h in hosts if not h.is_mongos]
    results = parallel_host_check(
        lambda h: _check_host(client, project_id, h), mongod_hosts
    )
    section.hosts = [hs for hs in results if hs is not None]
    return section


def _check_host(client: HealthCheckClient, project_id: str, host: Host) -> HostSection:
    hs = HostSection(
        host=host.host_port,
        role=host.replica_state_name or host.type_name or "UNKNOWN",
    )

    disks = client.om.deployments.list_disks(project_id, host.id)

    for disk in disks:
        metrics = fetch_disk_metrics(
            client.om, project_id, host.id,
            disk.partition_name, _DISK_METRICS,
        )
        for metric_name in _DISK_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(
                Check(
                    name=f"{metric_name} [{disk.partition_name}]",
                    status=result.status,
                    value=result.current_value,
                    units=_UNITS.get(metric_name, ""),
                    baseline_value=result.baseline_value,
                    baseline_deviation=result.deviation,
                    threshold=result.threshold.red if result.threshold else None,
                    message=result.message,
                )
            )

    # CPU iowait correlation — cross-reference from compute metrics
    iowait_metrics = fetch_host_metrics(
        client.om, project_id, host.id, ["SYSTEM_NORMALIZED_CPU_IOWAIT"]
    )
    iowait_current, iowait_baseline = iowait_metrics.get(
        "SYSTEM_NORMALIZED_CPU_IOWAIT", (None, None)
    )
    if iowait_current is not None:
        iowait_result = evaluate_metric(
            "SYSTEM_NORMALIZED_CPU_IOWAIT", iowait_current, iowait_baseline
        )
        disk_has_red = any(c.status == STATUS_RED for c in hs.checks)
        if disk_has_red and iowait_result.status in (STATUS_RED, STATUS_WARN):
            hs.checks.append(
                Check(
                    name="CPU iowait correlation",
                    status=iowait_result.status,
                    value=iowait_current,
                    units="%",
                    message=f"Elevated iowait ({iowait_current:.1f}%) "
                    "correlates with disk pressure",
                )
            )

    return hs
