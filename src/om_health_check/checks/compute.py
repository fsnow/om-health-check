"""Section 2: Compute Resources checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.concurrency import parallel_host_check
from om_health_check.models import STATUS_INFO, STATUS_RED, Check, HostSection, Section

_TOP_LEVEL_METRICS = [
    "SYSTEM_NORMALIZED_CPU_USER",
    "SYSTEM_NORMALIZED_CPU_IOWAIT",
    "PROCESS_NORMALIZED_CPU_USER",
    "SYSTEM_MEMORY_AVAILABLE",
    "MEMORY_RESIDENT",
    "SWAP_USAGE_USED",
]

_DEEPER_CPU_METRICS = [
    "SYSTEM_NORMALIZED_CPU_STEAL",
    "SYSTEM_NORMALIZED_CPU_GUEST",
    "SYSTEM_NORMALIZED_CPU_SOFTIRQ",
    "SYSTEM_NORMALIZED_CPU_IRQ",
    "SYSTEM_NORMALIZED_CPU_NICE",
    "SYSTEM_NORMALIZED_CPU_KERNEL",
]

_DEEPER_MEM_METRICS = [
    "SWAP_USAGE_FREE",
]

_UNITS = {
    "SYSTEM_NORMALIZED_CPU_USER": "%",
    "SYSTEM_NORMALIZED_CPU_IOWAIT": "%",
    "PROCESS_NORMALIZED_CPU_USER": "%",
    "SYSTEM_MEMORY_AVAILABLE": "MB",
    "MEMORY_RESIDENT": "MB",
    "SWAP_USAGE_USED": "MB",
    "SWAP_USAGE_FREE": "MB",
}


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Compute Resources")
    section.hosts = parallel_host_check(
        lambda h: _check_host(client, project_id, h), hosts
    )
    return section


def _check_host(client: HealthCheckClient, project_id: str, host: Host) -> HostSection:
    hs = HostSection(
        host=host.host_port,
        role=host.replica_state_name or host.type_name or "UNKNOWN",
    )
    metrics = fetch_host_metrics(client.om, project_id, host.id, _TOP_LEVEL_METRICS)
    any_red = False
    for metric_name in _TOP_LEVEL_METRICS:
        current, baseline = metrics.get(metric_name, (None, None))
        result = evaluate_metric(metric_name, current, baseline)
        if result.status == STATUS_RED:
            any_red = True
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

    # Deeper analysis if any top-level check is RED
    if any_red:
        deeper_metrics = fetch_host_metrics(
            client.om, project_id, host.id,
            _DEEPER_CPU_METRICS + _DEEPER_MEM_METRICS,
        )
        for metric_name in _DEEPER_CPU_METRICS + _DEEPER_MEM_METRICS:
            current, baseline = deeper_metrics.get(metric_name, (None, None))
            if current is None:
                continue
            deviation = None
            if baseline is not None and baseline > 0:
                deviation = current / baseline
            hs.checks.append(
                Check(
                    name=metric_name,
                    status=STATUS_INFO,
                    value=current,
                    units=_UNITS.get(metric_name, "%"),
                    baseline_value=baseline,
                    baseline_deviation=deviation,
                    message=f"{current:,.2f}"
                    + (f" (baseline: {baseline:,.2f})" if baseline is not None else ""),
                )
            )
    return hs
