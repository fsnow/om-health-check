"""Orchestrator: iterates projects/clusters, runs all check sections, renders output."""

from __future__ import annotations

import sys

from om_health_check.client import HealthCheckClient
from om_health_check.config import Config
from om_health_check.models import (
    STATUS_RED,
    Check,
    ClusterReport,
    Report,
    Section,
)
from om_health_check.checks import connectivity, compute, disk, cache, workload
from om_health_check.checks import replication, connections, backup, version
from om_health_check.renderers import txt, json_renderer, html

# Ordered list of check sections
CHECK_SECTIONS = [
    ("Connectivity & Infrastructure", connectivity.run),
    ("Compute Resources", compute.run),
    ("Disk Resources", disk.run),
    ("Cache Resources", cache.run),
    ("Database Activity & Workload", workload.run),
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
    report = Report(om_url=config.om_url)

    try:
        client = HealthCheckClient(config)
    except Exception as exc:
        # Client init failure — connectivity RED
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
                        message=f"Failed to connect: {exc}",
                    )
                ],
            )
        )
        report.clusters.append(cluster_report)
        _render(report, config)
        return report

    with client:
        for project_name in config.project_names:
            try:
                project = client.resolve_project(project_name)
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
    )

    for section_name, check_fn in CHECK_SECTIONS:
        try:
            section = check_fn(client, project.id, cluster, hosts)
            cr.sections.append(section)
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


def _render(report: Report, config: Config):
    """Render the report in all requested formats.

    Single format prints to stdout. Multiple formats write to separate files.
    """
    if len(config.formats) == 1:
        renderer = RENDERERS.get(config.formats[0])
        if renderer:
            print(renderer(report))
        return

    for fmt in config.formats:
        renderer = RENDERERS.get(fmt)
        if renderer:
            filename = f"om-health-check-report.{fmt}"
            with open(filename, "w") as f:
                f.write(renderer(report))
            print(f"Wrote {filename}", file=sys.stderr)
