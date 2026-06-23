"""Orchestrator: iterates projects/clusters, runs all check sections, renders output."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from opsmanager.errors import OpsManagerAuthenticationError, OpsManagerForbiddenError

from om_health_check.client import HealthCheckClient
from om_health_check.config import Config
from om_health_check.models import (
    STATUS_RED,
    Check,
    ClusterReport,
    Report,
    Section,
    Topology,
)
from om_health_check.checks import connectivity, compute, disk, cache, workload
from om_health_check.checks import oplog, replication, connections, backup, version
from om_health_check.renderers import txt, json_renderer, html

_PERMISSION_HINT = (
    "The API key requires the Project Read Only role. "
    "See: https://www.mongodb.com/docs/ops-manager/current/reference/user-roles/"
)

# Ordered list of check sections
CHECK_SECTIONS = [
    ("Connectivity & Infrastructure", connectivity.run),
    ("Compute Resources", compute.run),
    ("Disk Resources", disk.run),
    ("Cache Resources", cache.run),
    ("Database Activity & Workload", workload.run),
    ("Oplog", oplog.run),
    ("Replication", replication.run),
    ("Connections", connections.run),
    ("Backup", backup.run),
    ("Version Information", version.run),
]

RENDERERS = {
    "txt": txt.render,
    "json": json_renderer.render,
    "html": html.render,
}


def run(config: Config) -> Report:
    """Run health checks and render output."""
    # Reset per-run state
    from om_health_check.baseline import _warned_metrics, parse_lookback, set_baseline_lookback
    from om_health_check.concurrency import set_max_workers
    from om_health_check.checks.workload import _reset_pa_state
    _warned_metrics.clear()
    _reset_pa_state()
    if config.baseline_lookback:
        set_baseline_lookback(parse_lookback(config.baseline_lookback))
    set_max_workers(config.max_workers)

    report = Report(om_url=config.om_url)

    try:
        client = HealthCheckClient(config)
    except Exception as exc:
        # Client init failure — connectivity RED
        message = f"Failed to connect: {exc}"
        if isinstance(exc, OpsManagerAuthenticationError):
            message = f"Authentication failed — check OPS_MANAGER_USER and OPS_MANAGER_API_KEY. {exc}"
        elif isinstance(exc, OpsManagerForbiddenError):
            message = f"Access denied. {_PERMISSION_HINT} ({exc})"
        cluster_report = ClusterReport(
            cluster_name="N/A",
            cluster_id="N/A",
            project_name=", ".join(config.project_names),
            project_id="N/A",
        )
        cluster_report.sections.append(
            Section(
                name="Connectivity & Infrastructure",
                cluster_checks=[
                    Check(
                        name="OM API reachability",
                        status=STATUS_RED,
                        message=message,
                    )
                ],
            )
        )
        report.clusters.append(cluster_report)
        report.finished_at = datetime.now(timezone.utc).isoformat()
        _render(report, config)
        return report

    with client:
        for project_name in config.project_names:
            try:
                project = client.resolve_project(project_name)
            except (OpsManagerAuthenticationError, OpsManagerForbiddenError) as exc:
                cluster_report = ClusterReport(
                    cluster_name="N/A",
                    cluster_id="N/A",
                    project_name=project_name,
                    project_id="N/A",
                )
                cluster_report.sections.append(
                    Section(
                        name="Connectivity & Infrastructure",
                        cluster_checks=[
                            Check(
                                name="Project resolution",
                                status=STATUS_RED,
                                message=f"Permission denied for project '{project_name}'. {_PERMISSION_HINT}",
                            )
                        ],
                    )
                )
                report.clusters.append(cluster_report)
                continue
            except Exception as exc:
                cluster_report = ClusterReport(
                    cluster_name="N/A",
                    cluster_id="N/A",
                    project_name=project_name,
                    project_id="N/A",
                )
                cluster_report.sections.append(
                    Section(
                        name="Connectivity & Infrastructure",
                        cluster_checks=[
                            Check(
                                name="Project resolution",
                                status=STATUS_RED,
                                message=f"Failed to resolve project '{project_name}': {exc}",
                            )
                        ],
                    )
                )
                report.clusters.append(cluster_report)
                continue

            try:
                clusters = client.get_clusters(project.id, config.cluster_name)
            except Exception as exc:
                cluster_report = ClusterReport(
                    cluster_name=config.cluster_name or "N/A",
                    cluster_id="N/A",
                    project_name=project.name,
                    project_id=project.id,
                )
                cluster_report.sections.append(
                    Section(
                        name="Connectivity & Infrastructure",
                        cluster_checks=[
                            Check(
                                name="Cluster resolution",
                                status=STATUS_RED,
                                message=f"Failed to list clusters: {exc}",
                            )
                        ],
                    )
                )
                report.clusters.append(cluster_report)
                continue

            for cluster in clusters:
                cluster_report = _check_cluster(client, project, cluster)
                report.clusters.append(cluster_report)

    report.finished_at = datetime.now(timezone.utc).isoformat()
    _render(report, config)
    return report


def _check_cluster(client, project, cluster) -> ClusterReport:
    """Run all check sections for a single cluster."""
    try:
        hosts = client.get_hosts_for_cluster(project.id, cluster.id)
    except Exception as exc:
        cr = ClusterReport(
            cluster_name=cluster.cluster_name,
            cluster_id=cluster.id,
            project_name=project.name,
            project_id=project.id,
        )
        cr.sections.append(
            Section(
                name="Connectivity & Infrastructure",
                cluster_checks=[
                    Check(
                        name="Host discovery",
                        status=STATUS_RED,
                        message=f"Failed to list hosts: {exc}",
                    )
                ],
            )
        )
        return cr

    cr = ClusterReport(
        cluster_name=cluster.cluster_name,
        cluster_id=cluster.id,
        project_name=project.name,
        project_id=project.id,
        topology=_compute_topology(cluster, hosts),
    )

    for section_name, check_fn in CHECK_SECTIONS:
        try:
            section = check_fn(client, project.id, cluster, hosts)
            cr.sections.append(section)
        except (OpsManagerAuthenticationError, OpsManagerForbiddenError) as exc:
            cr.sections.append(
                Section(
                    name=section_name,
                    cluster_checks=[
                        Check(
                            name=section_name,
                            status=STATUS_RED,
                            message=f"Permission denied for {section_name}. {_PERMISSION_HINT}",
                        )
                    ],
                )
            )
        except Exception as exc:
            cr.sections.append(
                Section(
                    name=section_name,
                    cluster_checks=[
                        Check(
                            name=section_name,
                            status=STATUS_RED,
                            message=f"Check failed: {exc}",
                        )
                    ],
                )
            )

    return cr


def _compute_topology(cluster, hosts) -> Topology:
    """Summarize cluster shape: total nodes, role mix, and shard count."""
    role_counts: dict[str, int] = {}
    shard_names: set[str] = set()
    cluster_type = getattr(cluster, "type_name", "") or "REPLICA_SET"
    for h in hosts:
        role = h.replica_state_name or h.type_name or "UNKNOWN"
        role_counts[role] = role_counts.get(role, 0) + 1
        # shardName is the right discriminator: per-shard for shard data nodes,
        # null for config servers + mongos
        shard_name = getattr(h, "shard_name", None)
        if shard_name:
            shard_names.add(shard_name)
    shard_count = len(shard_names) if cluster_type == "SHARDED_REPLICA_SET" else 0
    return Topology(
        node_count=len(hosts),
        cluster_type=cluster_type,
        role_counts=role_counts,
        shard_count=shard_count,
    )


def _render(report: Report, config: Config):
    """Render the report in all requested formats.

    Single format prints to stdout. Multiple formats write to separate files.
    --min-status applies to txt output only.
    """
    if len(config.formats) == 1:
        fmt = config.formats[0]
        rendered = _render_one(report, fmt, config.min_status)
        if rendered is not None:
            print(rendered)
        return

    for fmt in config.formats:
        rendered = _render_one(report, fmt, config.min_status)
        if rendered is None:
            continue
        filename = f"om-health-check-report.{fmt}"
        with open(filename, "w") as f:
            f.write(rendered)
        print(f"Wrote {filename}", file=sys.stderr)


def _render_one(report: Report, fmt: str, min_status: str) -> str | None:
    renderer = RENDERERS.get(fmt)
    if renderer is None:
        return None
    if fmt == "txt":
        return renderer(report, min_status=min_status)
    return renderer(report)
