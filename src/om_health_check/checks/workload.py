"""Section 5: Database Activity & Workload checks."""

from __future__ import annotations

import time

from opsmanager.errors import OpsManagerAuthenticationError, OpsManagerForbiddenError
from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
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
    # Mongos has no opcounters / query metrics / global locks; skip those
    # hosts to avoid spurious "no data" rows and prevent the global "metrics
    # unavailable" dedup from poisoning the run for real mongod hosts.
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
    metrics = fetch_host_metrics(client.om, project_id, host.id, _ALL_METRICS)
    for metric_name in _ALL_METRICS:
        current, baseline = metrics.get(metric_name, (None, None))

        # Secondaries continuously issue getMores to tail the primary's oplog,
        # so an elevated OPCOUNTER_GETMORE there is expected replication traffic,
        # not a workload anomaly. Report the value as INFO instead of grading it.
        if metric_name == "OPCOUNTER_GETMORE" and host.is_secondary:
            value_str = f"{current:,.2f}" if current is not None else "no data"
            hs.checks.append(
                Check(
                    name=metric_name,
                    status=STATUS_INFO,
                    value=current,
                    units=_UNITS.get(metric_name, "ops/s"),
                    baseline_value=baseline,
                    message=(
                        f"{value_str} — not graded on secondaries "
                        "(expected from oplog tailing)"
                    ),
                )
            )
            continue

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
    _check_performance_advisor(client, project_id, host, hs)
    return hs


# Per-run state. Once the first PA call fails, subsequent hosts short-circuit
# with the cached message rather than re-calling — if PA is broken or
# inaccessible for one host in a project, it's broken/inaccessible for all of
# them. Reset at the start of each run.
_pa_failure_message: str | None = None


def _reset_pa_state() -> None:
    global _pa_failure_message
    _pa_failure_message = None


_PA_PERMISSION_HINT = (
    " (commonly caused by insufficient permissions — Performance Advisor "
    "requires Project Data Access Read Only role or higher)"
)


def _check_performance_advisor(
    client: HealthCheckClient,
    project_id: str,
    host: Host,
    hs: HostSection,
):
    """Check Performance Advisor for suggested indexes.

    We deliberately do not call the slowQueryLogs endpoint: it would transfer
    the full slow-query payload (query text, filter values, parameters) just
    to read the list length. Suggested indexes are derived from those same
    slow queries server-side, so we get the actionable signal without
    pulling potentially sensitive query content over the wire.

    Permissions: requires Project Data Access Read Only or higher. Many
    customers only grant Project Read Only to health-check users. After the
    first failure (401/403 OR 500 — OM sometimes returns the latter for
    unauthorized PA calls), we short-circuit subsequent hosts.
    """
    global _pa_failure_message
    if _pa_failure_message is not None:
        hs.checks.append(
            Check(name="Performance Advisor", status=STATUS_INFO,
                  message=_pa_failure_message)
        )
        return

    host_id = host.host_port
    now_ms = int(time.time() * 1000)
    one_hour_ms = 60 * 60 * 1000

    try:
        advisor_response = client.om.performance_advisor.get_suggested_indexes(
            project_id=project_id,
            host_id=host_id,
            since=now_ms - one_hour_ms,
            duration=one_hour_ms,
        )
        suggested_indexes = advisor_response.get("suggested_indexes", [])
    except (OpsManagerAuthenticationError, OpsManagerForbiddenError):
        _pa_failure_message = (
            "Performance Advisor access denied — requires Project "
            "Data Access Read Only role or higher"
        )
        hs.checks.append(
            Check(name="Performance Advisor", status=STATUS_INFO,
                  message=_pa_failure_message)
        )
        return
    except Exception as exc:
        # OM also returns 500 INTERNAL SERVER ERROR for PA — sometimes from
        # genuine internal errors (not enough query history, feature off,
        # OM restart) but also when the caller lacks PA permissions (the OM
        # permission check itself errors before returning 401).
        _pa_failure_message = (
            f"Performance Advisor unavailable: {exc}{_PA_PERMISSION_HINT}"[:300]
        )
        hs.checks.append(
            Check(name="Performance Advisor", status=STATUS_INFO,
                  message=_pa_failure_message)
        )
        return

    if suggested_indexes:
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
    else:
        hs.checks.append(
            Check(
                name="Performance Advisor",
                status=STATUS_GREEN,
                message="No index suggestions",
            )
        )
