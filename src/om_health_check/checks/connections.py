"""Section 7: Connections checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
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

    for host in hosts:
        hs = HostSection(
            host=host.host_port,
            role=host.replica_state_name or host.type_name or "UNKNOWN",
        )

        metrics = fetch_host_metrics(
            client.om, project_id, host.id, _METRICS + _LATENCY_METRICS
        )

        conn_current, conn_baseline = metrics.get("CONNECTIONS", (None, None))

        # Special case: connections = 0
        if conn_current is not None and conn_current == 0:
            hs.checks.append(
                Check(
                    name="CONNECTIONS",
                    status=STATUS_GREEN,
                    value=0,
                    units="connections",
                    baseline_value=conn_baseline,
                    message="0 connections — MongoDB is healthy. "
                    "Problem is upstream (load balancer, DNS, app config).",
                )
            )
        else:
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

            # Connection storm correlation: connections spiking + latency elevated
            if result.status == STATUS_RED and conn_current is not None:
                reads_current, reads_baseline = metrics.get(
                    "OP_EXECUTION_TIME_READS", (None, None)
                )
                writes_current, writes_baseline = metrics.get(
                    "OP_EXECUTION_TIME_WRITES", (None, None)
                )
                latency_elevated = False
                if reads_current is not None:
                    reads_result = evaluate_metric(
                        "OP_EXECUTION_TIME_READS", reads_current, reads_baseline
                    )
                    if reads_result.status in (STATUS_RED, STATUS_WARN):
                        latency_elevated = True
                if writes_current is not None:
                    writes_result = evaluate_metric(
                        "OP_EXECUTION_TIME_WRITES", writes_current, writes_baseline
                    )
                    if writes_result.status in (STATUS_RED, STATUS_WARN):
                        latency_elevated = True

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

        section.hosts.append(hs)

    return section
