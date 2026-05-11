"""Section 7: Connections checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
from om_health_check.models import (
    STATUS_GREEN,
    STATUS_INFO,
    STATUS_RED,
    STATUS_WARN,
    Check,
    HostSection,
    Section,
)

_METRICS = ["CONNECTIONS"]
_LATENCY_METRICS = ["OP_EXECUTION_TIME_READS", "OP_EXECUTION_TIME_WRITES"]


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Connections")
    section.hosts = parallel_host_check(
        lambda h: _check_host(client, project_id, h), hosts
    )
    return section


def _check_host(client: HealthCheckClient, project_id: str, host: Host) -> HostSection:
    hs = HostSection(
        host=host.host_port,
        role=host.replica_state_name or host.type_name or "UNKNOWN",
    )
    metrics = fetch_host_metrics(
        client.om, project_id, host.id, _METRICS + _LATENCY_METRICS
    )
    conn_current, conn_baseline = metrics.get("CONNECTIONS", (None, None))

    if conn_current is not None and conn_current == 0:
        hs.checks.append(
            Check(
                name="CONNECTIONS", status=STATUS_GREEN, value=0,
                units="connections", baseline_value=conn_baseline,
                message="0 connections — MongoDB is healthy. "
                "Problem is upstream (load balancer, DNS, app config).",
            )
        )
        return hs

    result = evaluate_metric("CONNECTIONS", conn_current, conn_baseline)
    hs.checks.append(
        Check(
            name="CONNECTIONS",
            status=result.status,
            value=result.current_value,
            units="connections",
            baseline_value=result.baseline_value,
            baseline_deviation=result.deviation,
            threshold=result.threshold.red if result.threshold else None,
            message=result.message,
        )
    )

    if result.status == STATUS_RED and conn_current is not None:
        latency_elevated = False
        for m in _LATENCY_METRICS:
            cur, base = metrics.get(m, (None, None))
            if cur is not None:
                r = evaluate_metric(m, cur, base)
                if r.status in (STATUS_RED, STATUS_WARN):
                    latency_elevated = True
                    break
        if latency_elevated:
            hs.checks.append(
                Check(
                    name="Connection storm correlation",
                    status=STATUS_INFO,
                    message="Connection spike correlates with elevated "
                    "operation latency — connection storm may be a "
                    "symptom, not the root cause.",
                )
            )
    return hs
