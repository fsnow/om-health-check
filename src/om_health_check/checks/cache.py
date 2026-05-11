"""Section 4: Cache Resources checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
from om_health_check.models import Check, HostSection, Section

_CACHE_METRICS = [
    "CACHE_USED_BYTES",
    "CACHE_DIRTY_BYTES",
    "CACHE_BYTES_READ_INTO",
    "CACHE_BYTES_WRITTEN_FROM",
]

_UNITS = {
    "CACHE_USED_BYTES": "bytes",
    "CACHE_DIRTY_BYTES": "bytes",
    "CACHE_BYTES_READ_INTO": "bytes",
    "CACHE_BYTES_WRITTEN_FROM": "bytes",
}


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Cache Resources")
    section.hosts = parallel_host_check(
        lambda h: _check_host(client, project_id, h), hosts
    )
    return section


def _check_host(client: HealthCheckClient, project_id: str, host: Host) -> HostSection:
    hs = HostSection(
        host=host.host_port,
        role=host.replica_state_name or host.type_name or "UNKNOWN",
    )
    metrics = fetch_host_metrics(client.om, project_id, host.id, _CACHE_METRICS)
    for metric_name in _CACHE_METRICS:
        current, baseline = metrics.get(metric_name, (None, None))
        result = evaluate_metric(metric_name, current, baseline)
        hs.checks.append(
            Check(
                name=metric_name,
                status=result.status,
                value=result.current_value,
                units=_UNITS.get(metric_name, ""),
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message,
            )
        )
    return hs
