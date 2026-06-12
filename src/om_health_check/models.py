"""Result model for health check reports.

All check logic produces instances of this model tree.
All renderers consume it. No rendering logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


STATUS_RED = "RED"
STATUS_GREEN = "GREEN"
STATUS_INFO = "INFO"
STATUS_WARN = "WARN"

# Priority for "worst status" rollup
_STATUS_PRIORITY = {STATUS_GREEN: 0, STATUS_INFO: 1, STATUS_WARN: 2, STATUS_RED: 3}


def worst_status(*statuses: str) -> str:
    """Return the most severe status from the given values."""
    return max(statuses, key=lambda s: _STATUS_PRIORITY.get(s, -1))


@dataclass
class Check:
    """A single health check result.

    ``rollup=False`` means the check is shown in the report but excluded from
    section/cluster/overall status. Use for advisory items that shouldn't color
    the overall report (e.g. informational alerts about external config).
    """

    name: str
    status: str
    value: Any = None
    units: str = ""
    threshold: float | None = None
    baseline_value: float | None = None
    baseline_deviation: float | None = None
    message: str = ""
    rollup: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "units": self.units,
            "threshold": self.threshold,
            "baseline_value": self.baseline_value,
            "baseline_deviation": self.baseline_deviation,
            "message": self.message,
        }


@dataclass
class HostSection:
    """Check results for a single host within a section."""

    host: str
    role: str
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        # INFO is informational and never bubbles up. Individual checks can
        # also opt out via rollup=False (escape hatch for suppressed WARN/RED).
        rollup_checks = [c for c in self.checks if c.rollup and c.status != STATUS_INFO]
        if not rollup_checks:
            return STATUS_GREEN
        return worst_status(*(c.status for c in rollup_checks))

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "role": self.role,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class Section:
    """A check section (e.g. 'Compute Resources') with per-host and cluster-level results."""

    name: str
    hosts: list[HostSection] = field(default_factory=list)
    cluster_checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        rollup_cluster_checks = [
            c.status for c in self.cluster_checks
            if c.rollup and c.status != STATUS_INFO
        ]
        statuses = [h.status for h in self.hosts] + rollup_cluster_checks
        if not statuses:
            return STATUS_GREEN
        return worst_status(*statuses)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "hosts": [h.to_dict() for h in self.hosts],
            "cluster_checks": [c.to_dict() for c in self.cluster_checks],
        }


@dataclass
class Topology:
    """Cluster shape — node count, type, role breakdown."""

    node_count: int = 0
    cluster_type: str = ""        # e.g. REPLICA_SET, SHARDED_REPLICA_SET
    role_counts: dict[str, int] = field(default_factory=dict)
    shard_count: int = 0          # 0 for non-sharded

    def summary_line(self) -> str:
        roles = ", ".join(
            f"{count} {role}"
            for role, count in sorted(self.role_counts.items(), key=lambda x: (-x[1], x[0]))
        )
        parts = [f"{self.node_count} nodes"]
        if self.cluster_type and self.cluster_type != "REPLICA_SET":
            parts.append(f"({self.cluster_type})")
        if self.shard_count:
            shard_word = "shard" if self.shard_count == 1 else "shards"
            parts.append(f"— {self.shard_count} {shard_word},")
        if roles:
            connector = "" if (self.shard_count or self.cluster_type != "REPLICA_SET") else "—"
            parts.append(f"{connector} {roles}".lstrip())
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {
            "node_count": self.node_count,
            "cluster_type": self.cluster_type,
            "role_counts": self.role_counts,
            "shard_count": self.shard_count,
        }


@dataclass
class ClusterReport:
    """Health check results for a single cluster."""

    cluster_name: str
    cluster_id: str
    project_name: str
    project_id: str
    timestamp: str = ""
    topology: Topology | None = None
    sections: list[Section] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def overall_status(self) -> str:
        if not self.sections:
            return STATUS_GREEN
        return worst_status(*(s.status for s in self.sections))

    def to_dict(self) -> dict:
        return {
            "cluster_name": self.cluster_name,
            "cluster_id": self.cluster_id,
            "project_name": self.project_name,
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "topology": self.topology.to_dict() if self.topology else None,
            "overall_status": self.overall_status,
            "sections": [s.to_dict() for s in self.sections],
        }


@dataclass
class Report:
    """Top-level report containing results for one or more clusters."""

    om_url: str
    started_at: str = ""
    finished_at: str = ""
    clusters: list[ClusterReport] = field(default_factory=list)

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def overall_status(self) -> str:
        if not self.clusters:
            return STATUS_GREEN
        return worst_status(*(c.overall_status for c in self.clusters))

    @property
    def elapsed_seconds(self) -> float | None:
        """Wall-clock seconds from started_at to finished_at, or None if not finished."""
        if not self.finished_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.finished_at)
        return (end - start).total_seconds()

    def to_dict(self) -> dict:
        return {
            "om_url": self.om_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "overall_status": self.overall_status,
            "clusters": [c.to_dict() for c in self.clusters],
        }
