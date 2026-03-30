"""Section 5: Database Activity & Workload checks."""

from __future__ import annotations

import time

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.models import STATUS_GREEN, STATUS_INFO, STATUS_RED, Check, HostSection, Section

_TARGETING_METRICS = [
    "QUERY_TARGETING_SCANNED_PER_RETURNED",
    "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED",
]

_EXECUTOR_METRICS = [
    "QUERY_EXECUTOR_SCANNED",
    "QUERY_EXECUTOR_SCANNED_OBJECTS",
]

_DOCUMENT_METRICS = [
    "DOCUMENT_METRICS_RETURNED",
    "DOCUMENT_METRICS_INSERTED",
    "DOCUMENT_METRICS_UPDATED",
    "DOCUMENT_METRICS_DELETED",
]

_SCAN_METRICS = [
    "OPERATIONS_SCAN_AND_ORDER",
]

_OPCOUNTER_METRICS = [
    "OPCOUNTER_CMD",
    "OPCOUNTER_QUERY",
    "OPCOUNTER_UPDATE",
    "OPCOUNTER_DELETE",
    "OPCOUNTER_GETMORE",
    "OPCOUNTER_INSERT",
]

_EXECUTION_TIME_METRICS = [
    "OP_EXECUTION_TIME_READS",
    "OP_EXECUTION_TIME_WRITES",
    "OP_EXECUTION_TIME_COMMANDS",
]

_QUEUE_METRICS = [
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS",
    "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS",
    "GLOBAL_LOCK_CURRENT_QUEUE_TOTAL",
]

_ALL_METRICS = (
    _TARGETING_METRICS
    + _EXECUTOR_METRICS
    + _DOCUMENT_METRICS
    + _SCAN_METRICS
    + _OPCOUNTER_METRICS
    + _EXECUTION_TIME_METRICS
    + _QUEUE_METRICS
)

_UNITS = {
    "QUERY_TARGETING_SCANNED_PER_RETURNED": "ratio",
    "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED": "ratio",
    "OP_EXECUTION_TIME_READS": "ms",
    "OP_EXECUTION_TIME_WRITES": "ms",
    "OP_EXECUTION_TIME_COMMANDS": "ms",
}


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Database Activity & Workload")

    for host in hosts:
        hs = HostSection(
            host=host.host_port,
            role=host.replica_state_name or host.type_name or "UNKNOWN",
        )

        metrics = fetch_host_metrics(
            client.om, project_id, host.id, _ALL_METRICS
        )

        for metric_name in _ALL_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(
                Check(
                    name=metric_name,
                    status=result.status,
                    value=result.current_value,
                    units=_UNITS.get(metric_name, "ops/s"),
                    baseline_value=result.baseline_value,
                    baseline_deviation=result.deviation,
                    threshold=result.threshold.red if result.threshold else None,
                    message=result.message,
                )
            )

        # Performance Advisor
        _check_performance_advisor(client, project_id, host, hs)

        section.hosts.append(hs)

    return section


def _check_performance_advisor(
    client: HealthCheckClient,
    project_id: str,
    host: Host,
    hs: HostSection,
):
    """Check Performance Advisor for slow queries and index suggestions."""
    host_id = host.host_port
    now_ms = int(time.time() * 1000)
    one_hour_ms = 60 * 60 * 1000

    try:
        slow_queries = client.om.performance_advisor.get_slow_queries(
            project_id=project_id,
            host_id=host_id,
            since=now_ms - one_hour_ms,
            duration=one_hour_ms,
        )
        suggested_indexes = client.om.performance_advisor.get_suggested_indexes(
            project_id=project_id,
            host_id=host_id,
            since=now_ms - one_hour_ms,
            duration=one_hour_ms,
        )
    except Exception:
        hs.checks.append(
            Check(
                name="Performance Advisor",
                status=STATUS_INFO,
                message="Performance Advisor data unavailable",
            )
        )
        return

    has_slow = bool(slow_queries)
    has_suggestions = bool(suggested_indexes)

    if has_suggestions:
        namespaces = {idx.namespace for idx in suggested_indexes}
        hs.checks.append(
            Check(
                name="Performance Advisor — suggested indexes",
                status=STATUS_RED,
                value=len(suggested_indexes),
                message=f"{len(suggested_indexes)} index suggestion(s) for: "
                + ", ".join(sorted(namespaces)),
            )
        )
    elif has_slow:
        hs.checks.append(
            Check(
                name="Performance Advisor — slow queries",
                status=STATUS_RED,
                value=len(slow_queries),
                message=f"{len(slow_queries)} slow query log(s) in last hour",
            )
        )
    else:
        hs.checks.append(
            Check(
                name="Performance Advisor",
                status=STATUS_GREEN,
                message="No slow queries or index suggestions",
            )
        )
