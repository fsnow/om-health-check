"""Thin wrapper around OpsManagerClient for project/cluster/host resolution."""

from __future__ import annotations

from opsmanager import OpsManagerClient
from opsmanager.types import Cluster, Host, Project

from om_health_check.config import Config


class HealthCheckClient:
    """Wraps OpsManagerClient with convenience methods for health check workflows."""

    def __init__(self, config: Config):
        # Pool sized to worker count, but never below urllib3's default (10)
        # so low --max-workers settings don't shrink it.
        pool_size = max(config.max_workers, 10)
        self.om = OpsManagerClient(
            base_url=config.om_url,
            public_key=config.username,
            private_key=config.api_key,
            rate_limit=config.rate_limit,
            pool_size=pool_size,
        )

    def close(self):
        self.om.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def resolve_project(self, project_name: str) -> Project:
        """Resolve a project name to a Project object. Raises on not found."""
        return self.om.projects.get_by_name(project_name)

    def get_clusters(
        self, project_id: str, cluster_name: str | None = None
    ) -> list[Cluster]:
        """List clusters in a project, optionally filtered by name.

        For sharded deployments OM returns one entry per shard replica set,
        one per config-server replica set, AND one for the parent sharded
        cluster — all sharing the same ``cluster_name``. We exclude the
        children (shard RSes have ``shard_name`` set; config-server RSes have
        type ``CONFIG_SERVER_REPLICA_SET``) because the parent's host list
        already covers all of them.
        """
        clusters = self.om.clusters.list(project_id)
        clusters = [
            c for c in clusters
            if not getattr(c, "shard_name", None)
            and getattr(c, "type_name", "") != "CONFIG_SERVER_REPLICA_SET"
        ]
        if cluster_name:
            clusters = [c for c in clusters if c.cluster_name == cluster_name]
            if not clusters:
                raise ValueError(
                    f"Cluster '{cluster_name}' not found in project {project_id}"
                )
        return clusters

    def get_hosts_for_cluster(
        self, project_id: str, cluster_id: str
    ) -> list[Host]:
        """Get all hosts belonging to a specific cluster."""
        return self.om.deployments.list_hosts(project_id, cluster_id=cluster_id)
