"""Section: Oplog (window + write rate, per replica member).

Separated from Replication because oplog window/rate and replication lag
are unrelated dimensions — a tight oplog window says nothing about whether
secondaries are caught up, and high lag says nothing about how much the
oplog can hold.
"""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
from om_health_check.models import Check, HostSection, Section

_METRICS = [
    "OPLOG_MASTER_TIME",
    "OPLOG_RATE_GB_PER_HOUR",
]

_UNITS = {
    "OPLOG_MASTER_TIME": "hours",
    "OPLOG_RATE_GB_PER_HOUR": "GB/hr",
}


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Oplog")
    replica_members = [h for h in hosts if h.is_primary or h.is_secondary]
    results = parallel_host_check(
        lambda h: _check_host(client, project_id, h), replica_members
    )
    section.hosts = [hs for hs in results if hs is not None]
    return section


def _check_host(client: HealthCheckClient, project_id: str, host: Host):
    hs = HostSection(
        host=host.host_port,
        role=host.replica_state_name or host.type_name or "UNKNOWN",
    )
    metrics = fetch_host_metrics(client.om, project_id, host.id, _METRICS)
    for metric_name in _METRICS:
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
