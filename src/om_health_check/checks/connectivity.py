"""Section 1: Connectivity & Infrastructure checks."""

from __future__ import annotations

from opsmanager.types import Cluster, Host

from om_health_check.baseline import evaluate_metric, fetch_host_metrics
from om_health_check.client import HealthCheckClient
from om_health_check.models import (
    STATUS_GREEN,
    STATUS_INFO,
    STATUS_RED,
    Check,
    HostSection,
    Section,
)


# Host-level metrics to fetch
_SYSTEM_NETWORK_METRICS = [
    "SYSTEM_NETWORK_IN",
    "SYSTEM_NETWORK_OUT",
]

_PROCESS_NETWORK_METRICS = [
    "NETWORK_BYTES_IN",
    "NETWORK_BYTES_OUT",
    "NETWORK_NUM_REQUESTS",
]

_HOST_METRICS = _PROCESS_NETWORK_METRICS + _SYSTEM_NETWORK_METRICS


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Connectivity & Infrastructure")

    # OM API reachability — already confirmed if we got this far
    section.cluster_checks.append(
        Check(name="OM API reachability", status=STATUS_GREEN, message="Connected")
    )

    # Active alerts — project-scoped, filtered to cluster
    _check_alerts(client, project_id, cluster, hosts, section)

    # Agent status
    _check_agents(client, project_id, hosts, section)

    # Per-host checks
    for host in hosts:
        hs = HostSection(
            host=host.host_port,
            role=host.replica_state_name or host.type_name or "UNKNOWN",
        )

        # Node status
        if not host.host_enabled:
            hs.checks.append(
                Check(name="Node status", status=STATUS_RED, message="Host is disabled")
            )
        elif host.replica_state_name and "DOWN" in host.replica_state_name.upper():
            hs.checks.append(
                Check(
                    name="Node status",
                    status=STATUS_RED,
                    message=f"Node state: {host.replica_state_name}",
                )
            )
        else:
            hs.checks.append(
                Check(
                    name="Node status",
                    status=STATUS_GREEN,
                    message=f"Node state: {host.replica_state_name or 'OK'}",
                )
            )

        # Metric-based checks
        metrics = fetch_host_metrics(
            client.om, project_id, host.id, _HOST_METRICS
        )

        # Network metrics — baseline comparison
        for metric_name in _SYSTEM_NETWORK_METRICS + _PROCESS_NETWORK_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(
                Check(
                    name=metric_name,
                    status=result.status,
                    value=result.current_value,
                    units="bytes" if "NETWORK" in metric_name else "requests",
                    baseline_value=result.baseline_value,
                    baseline_deviation=result.deviation,
                    threshold=result.threshold.red if result.threshold else None,
                    message=result.message,
                )
            )

        section.hosts.append(hs)

    return section


def _check_alerts(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
    section: Section,
):
    """Check for open alerts scoped to this cluster."""
    alerts = client.om.alerts.list_open(project_id)

    # Filter to cluster by hostname or cluster name
    host_ports = {h.host_port for h in hosts}
    cluster_alerts = []
    for alert in alerts:
        if alert.cluster_name and alert.cluster_name == cluster.cluster_name:
            cluster_alerts.append(alert)
        elif alert.hostname_and_port and alert.hostname_and_port in host_ports:
            cluster_alerts.append(alert)

    if cluster_alerts:
        for alert in cluster_alerts:
            section.cluster_checks.append(
                Check(
                    name="Active alert",
                    status=STATUS_RED,
                    message=(
                        f"[{alert.event_type_name}] "
                        f"{alert.hostname_and_port or alert.cluster_name or ''} — "
                        f"{alert.metric_name or alert.event_type_name} "
                        f"(since {alert.created})"
                    ),
                )
            )
    else:
        section.cluster_checks.append(
            Check(
                name="Active alerts",
                status=STATUS_GREEN,
                message="No open alerts for this cluster",
            )
        )


def _check_agents(
    client: HealthCheckClient,
    project_id: str,
    hosts: list[Host],
    section: Section,
):
    """Check monitoring agent status for hosts in this cluster."""
    agents = client.om.agents.list_monitoring(project_id)

    host_hostnames = {h.hostname for h in hosts}
    cluster_agents = [a for a in agents if a.hostname in host_hostnames]

    if not cluster_agents:
        section.cluster_checks.append(
            Check(
                name="Agent status",
                status=STATUS_RED,
                message="No monitoring agents found for cluster hosts",
            )
        )
        return

    for agent in cluster_agents:
        if agent.state_name == "ACTIVE":
            status = STATUS_GREEN
            msg = f"{agent.hostname}: ACTIVE"
        else:
            status = STATUS_RED
            msg = f"{agent.hostname}: {agent.state_name} (last ping: {agent.last_ping})"

        section.cluster_checks.append(
            Check(name="Agent status", status=status, message=msg)
        )
