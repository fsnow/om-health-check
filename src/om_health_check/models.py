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
    """A single health check result."""

    name: str
    status: str
    value: Any = None
    units: str = ""
    threshold: float | None = None
    baseline_value: float | None = None
    baseline_deviation: float | None = None
    message: str = ""

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
        if not self.checks:
            return STATUS_GREEN
        return worst_status(*(c.status for c in self.checks))

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
        statuses = [h.status for h in self.hosts] + [c.status for c in self.cluster_checks]
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
class ClusterReport:
    """Health check results for a single cluster."""

    cluster_name: str
    cluster_id: str
    project_name: str
    project_id: str
    timestamp: str = ""
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
            "overall_status": self.overall_status,
            "sections": [s.to_dict() for s in self.sections],
        }


@dataclass
class Report:
    """Top-level report containing results for one or more clusters."""

    om_url: str
    generated_at: str = ""
    clusters: list[ClusterReport] = field(default_factory=list)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    @property
    def overall_status(self) -> str:
        if not self.clusters:
            return STATUS_GREEN
        return worst_status(*(c.overall_status for c in self.clusters))

    def to_dict(self) -> dict:
        return {
            "om_url": self.om_url,
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "clusters": [c.to_dict() for c in self.clusters],
        }
