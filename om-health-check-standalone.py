#!/usr/bin/env python3
# Copyright 2026 Frank Snow
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
om-health-check — standalone single-file edition.

Flattened equivalent of the om-health-check package with the opsmanager API
client inlined. Intended for environments where installing from PyPI is not
an option.

Source:  https://github.com/fsnow/om-health-check
Version: see __version__ below

Runtime requirements (must be importable):
    Python 3.10+, requests, jinja2, packaging, pyyaml

Usage:
    export OPS_MANAGER_USER=<public-key>
    export OPS_MANAGER_API_KEY=<private-key>
    python3 om-health-check-standalone.py --om-url URL --project NAME

File layout (top-to-bottom):
    SECTION 1: Inlined opsmanager client  (errors, types, HTTP, services)
    SECTION 2: Result models              (Check, Section, HostSection, ...)
    SECTION 3: Threshold config           (defaults + YAML override loading)
    SECTION 4: Baseline fetch & evaluate  (core comparison engine)
    SECTION 5: Check modules              (9 sections, one function each)
    SECTION 6: Renderers                  (txt, json, html)
    SECTION 7: Runner + CLI
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests
from requests.auth import HTTPDigestAuth
from jinja2 import Environment
from packaging.version import Version, InvalidVersion

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


__version__ = "0.2.0"

# Suppress verbose HTTP error logs; we summarize failures ourselves.
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.getLogger("requests").setLevel(logging.CRITICAL)


# =============================================================================
# SECTION 1: Inlined opsmanager client
# =============================================================================
#
# Minimal subset of the opsmanager package covering only the 13 endpoints the
# health check needs. Uses HTTP Digest authentication per OM API requirements.
#
# Types are stripped-down dataclasses mirroring the attributes the check code
# accesses. `from_dict()` class methods translate OM JSON responses.
# -----------------------------------------------------------------------------


# -- Errors -------------------------------------------------------------------

class OpsManagerError(Exception):
    """Base exception for Ops Manager API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 error_code: Optional[str] = None, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail

    def __str__(self) -> str:
        parts = [self.message]
        if self.error_code:
            parts.append(f"[{self.error_code}]")
        if self.detail:
            parts.append(f"- {self.detail}")
        return " ".join(parts)


class OpsManagerAuthenticationError(OpsManagerError):
    """HTTP 401 — invalid or missing credentials."""


class OpsManagerForbiddenError(OpsManagerError):
    """HTTP 403 — caller lacks permission for the requested resource."""


class OpsManagerNotFoundError(OpsManagerError):
    """HTTP 404 — resource not found (includes INVALID_METRIC_NAME)."""


def _raise_for_status(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body = resp.json()
    except Exception:
        body = {}
    msg = body.get("reason") or resp.reason or f"HTTP {resp.status_code}"
    error_code = body.get("errorCode", "")
    detail = body.get("detail", "")
    sc = resp.status_code
    cls = {
        401: OpsManagerAuthenticationError,
        403: OpsManagerForbiddenError,
        404: OpsManagerNotFoundError,
    }.get(sc, OpsManagerError)
    raise cls(msg, status_code=sc, error_code=error_code, detail=detail)


# -- Types --------------------------------------------------------------------

@dataclass
class Project:
    id: str
    name: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Project":
        return cls(id=d.get("id", ""), name=d.get("name", ""))


@dataclass
class Cluster:
    id: str
    cluster_name: str
    type_name: str = ""
    replica_set_name: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Cluster":
        return cls(
            id=d.get("id", ""),
            cluster_name=d.get("clusterName", ""),
            type_name=d.get("typeName", ""),
            replica_set_name=d.get("replicaSetName"),
        )


@dataclass
class Host:
    id: str
    hostname: str
    port: int
    replica_state_name: str = ""
    host_enabled: bool = True
    version: str = ""
    cluster_id: str = ""
    type_name: str = ""

    @property
    def host_port(self) -> str:
        return f"{self.hostname}:{self.port}"

    @property
    def is_primary(self) -> bool:
        return self.replica_state_name == "PRIMARY"

    @property
    def is_secondary(self) -> bool:
        return self.replica_state_name == "SECONDARY"

    @property
    def is_arbiter(self) -> bool:
        return self.replica_state_name == "ARBITER"

    @property
    def is_mongos(self) -> bool:
        return "MONGOS" in self.type_name.upper() if self.type_name else False

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Host":
        return cls(
            id=d.get("id", ""),
            hostname=d.get("hostname", ""),
            port=d.get("port", 0),
            replica_state_name=d.get("replicaStateName", ""),
            host_enabled=d.get("hostEnabled", True),
            version=d.get("version", ""),
            cluster_id=d.get("clusterId", ""),
            type_name=d.get("typeName", ""),
        )


@dataclass
class Disk:
    partition_name: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Disk":
        return cls(partition_name=d.get("partitionName", ""))


@dataclass
class Alert:
    id: str
    event_type_name: str
    hostname_and_port: Optional[str] = None
    cluster_name: Optional[str] = None
    metric_name: Optional[str] = None
    created: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Alert":
        return cls(
            id=d.get("id", ""),
            event_type_name=d.get("eventTypeName", ""),
            hostname_and_port=d.get("hostnameAndPort"),
            cluster_name=d.get("clusterName"),
            metric_name=d.get("metricName"),
            created=d.get("created", ""),
        )


@dataclass
class Agent:
    hostname: str
    state_name: str = ""
    type_name: str = ""
    last_ping: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Agent":
        return cls(
            hostname=d.get("hostname", ""),
            state_name=d.get("stateName", ""),
            type_name=d.get("typeName", ""),
            last_ping=d.get("lastPing"),
        )


@dataclass
class DataPoint:
    timestamp: str
    value: Optional[float] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DataPoint":
        return cls(timestamp=d.get("timestamp", ""), value=d.get("value"))


@dataclass
class Measurement:
    name: str
    units: str = ""
    data_points: List[DataPoint] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Measurement":
        return cls(
            name=d.get("name", ""),
            units=d.get("units", ""),
            data_points=[DataPoint.from_dict(dp) for dp in d.get("dataPoints", [])],
        )


@dataclass
class ProcessMeasurements:
    measurements: List[Measurement] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProcessMeasurements":
        return cls(
            measurements=[Measurement.from_dict(m) for m in d.get("measurements", [])],
        )


@dataclass
class BackupConfig:
    cluster_id: str = ""
    status_name: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BackupConfig":
        return cls(
            cluster_id=d.get("clusterId", ""),
            status_name=d.get("statusName", ""),
        )


@dataclass
class SnapshotSchedule:
    snapshot_interval_hours: int = 6

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SnapshotSchedule":
        return cls(snapshot_interval_hours=d.get("snapshotIntervalHours", 6))


@dataclass
class SnapshotPart:
    replica_set_name: str = ""
    replica_state: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SnapshotPart":
        return cls(
            replica_set_name=d.get("replicaSetName", ""),
            replica_state=d.get("replicaState", ""),
        )


@dataclass
class Snapshot:
    id: str
    cluster_id: str = ""
    complete: bool = False
    created: Optional[Dict[str, Any]] = None
    parts: List[SnapshotPart] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Snapshot":
        return cls(
            id=d.get("id", ""),
            cluster_id=d.get("clusterId", ""),
            complete=d.get("complete", False),
            created=d.get("created"),
            parts=[SnapshotPart.from_dict(p) for p in d.get("parts", [])],
        )


@dataclass
class SuggestedIndex:
    namespace: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SuggestedIndex":
        return cls(namespace=d.get("namespace", ""))


# -- HTTP client --------------------------------------------------------------

class OpsManagerClient:
    """Minimal OM API client: digest auth + JSON GET + pagination."""

    def __init__(self, base_url: str, public_key: str, private_key: str,
                 timeout: int = 30):
        self.base_url = base_url.rstrip("/") + "/api/public/v1.0/"
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(public_key, private_key)
        self.session.headers["Accept"] = "application/json"
        self.timeout = timeout

        # Service namespaces — attached here so call sites read as
        # `client.measurements.host(...)`, matching the real opsmanager.
        self.projects = _ProjectsService(self)
        self.clusters = _ClustersService(self)
        self.deployments = _DeploymentsService(self)
        self.measurements = _MeasurementsService(self)
        self.alerts = _AlertsService(self)
        self.agents = _AgentsService(self)
        self.backup = _BackupService(self)
        self.performance_advisor = _PerformanceAdvisorService(self)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "OpsManagerClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        resp = self.session.get(url, params=params, timeout=self.timeout)
        _raise_for_status(resp)
        return resp.json()

    def _paginate(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Collect all items across paginated pages. Returns a flat list."""
        merged: List[Dict[str, Any]] = []
        params = dict(params or {})
        params.setdefault("itemsPerPage", 500)
        page = 1
        while True:
            params["pageNum"] = page
            data = self._get(path, params)
            batch = data.get("results", [])
            merged.extend(batch)
            total = data.get("totalCount", len(merged))
            if len(merged) >= total or not batch:
                break
            page += 1
        return merged


# -- Service namespaces -------------------------------------------------------

class _ProjectsService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def get_by_name(self, name: str) -> Project:
        return Project.from_dict(self._c._get(f"groups/byName/{name}"))


class _ClustersService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def list(self, project_id: str) -> List[Cluster]:
        return [Cluster.from_dict(d)
                for d in self._c._paginate(f"groups/{project_id}/clusters")]


class _DeploymentsService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def list_hosts(self, project_id: str,
                   cluster_id: Optional[str] = None) -> List[Host]:
        params: Dict[str, Any] = {}
        if cluster_id:
            params["clusterId"] = cluster_id
        return [Host.from_dict(d)
                for d in self._c._paginate(f"groups/{project_id}/hosts", params)]

    def list_disks(self, project_id: str, host_id: str) -> List[Disk]:
        return [Disk.from_dict(d)
                for d in self._c._paginate(
                    f"groups/{project_id}/hosts/{host_id}/disks")]


class _MeasurementsService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    @staticmethod
    def _check_time(period, start, end):
        if period and (start or end):
            raise ValueError("period and start/end are mutually exclusive")
        if bool(start) != bool(end):
            raise ValueError("start and end must both be provided")

    def host(self, project_id: str, host_id: str,
             granularity: str = "PT1M", period: Optional[str] = "P1D",
             start: Optional[str] = None, end: Optional[str] = None,
             metrics: Optional[List[str]] = None) -> ProcessMeasurements:
        self._check_time(period, start, end)
        params: Dict[str, Any] = {"granularity": granularity}
        if period:
            params["period"] = period
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if metrics:
            params["m"] = metrics
        data = self._c._get(f"groups/{project_id}/hosts/{host_id}/measurements",
                            params)
        return ProcessMeasurements.from_dict(data)

    def disk(self, project_id: str, host_id: str, partition_name: str,
             granularity: str = "PT1M", period: Optional[str] = "P1D",
             start: Optional[str] = None, end: Optional[str] = None,
             metrics: Optional[List[str]] = None) -> ProcessMeasurements:
        self._check_time(period, start, end)
        params: Dict[str, Any] = {"granularity": granularity}
        if period:
            params["period"] = period
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if metrics:
            params["m"] = metrics
        data = self._c._get(
            f"groups/{project_id}/hosts/{host_id}/disks/{partition_name}/measurements",
            params)
        return ProcessMeasurements.from_dict(data)


class _AlertsService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def list_open(self, project_id: str) -> List[Alert]:
        return [Alert.from_dict(d)
                for d in self._c._paginate(
                    f"groups/{project_id}/alerts", {"status": "OPEN"})]


class _AgentsService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def list_monitoring(self, project_id: str) -> List[Agent]:
        return [Agent.from_dict(d)
                for d in self._c._paginate(
                    f"groups/{project_id}/agents/MONITORING")]


class _BackupService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def get_backup_config(self, project_id: str, cluster_id: str) -> BackupConfig:
        return BackupConfig.from_dict(
            self._c._get(f"groups/{project_id}/backupConfigs/{cluster_id}"))

    def get_snapshot_schedule(self, project_id: str,
                              cluster_id: str) -> SnapshotSchedule:
        return SnapshotSchedule.from_dict(
            self._c._get(
                f"groups/{project_id}/clusters/{cluster_id}/snapshotSchedule"))

    def list_snapshots(self, project_id: str,
                       cluster_id: str) -> List[Snapshot]:
        return [Snapshot.from_dict(d)
                for d in self._c._paginate(
                    f"groups/{project_id}/clusters/{cluster_id}/snapshots")]


class _PerformanceAdvisorService:
    def __init__(self, client: OpsManagerClient):
        self._c = client

    def get_slow_queries(self, project_id: str, host_id: str,
                         since: Optional[int] = None,
                         duration: Optional[int] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if duration is not None:
            params["duration"] = duration
        data = self._c._get(
            f"groups/{project_id}/hosts/{host_id}/performanceAdvisor/slowQueryLogs",
            params)
        return data.get("slowQueries", [])

    def get_suggested_indexes(self, project_id: str, host_id: str,
                              since: Optional[int] = None,
                              duration: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if duration is not None:
            params["duration"] = duration
        data = self._c._get(
            f"groups/{project_id}/hosts/{host_id}/performanceAdvisor/suggestedIndexes",
            params)
        return {
            "suggested_indexes": [SuggestedIndex.from_dict(i)
                                  for i in data.get("suggestedIndexes", [])],
            "shapes": data.get("shapes", []),
        }


# =============================================================================
# SECTION 2: Result models
# =============================================================================
# Data structures produced by check modules and consumed by renderers.
# -----------------------------------------------------------------------------

STATUS_RED = "RED"
STATUS_GREEN = "GREEN"
STATUS_INFO = "INFO"
STATUS_WARN = "WARN"

_STATUS_PRIORITY = {STATUS_GREEN: 0, STATUS_INFO: 1, STATUS_WARN: 2, STATUS_RED: 3}


def worst_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: _STATUS_PRIORITY.get(s, -1))


@dataclass
class Check:
    """A single health check result.

    ``rollup=False`` means the check is shown in the report but excluded from
    section/cluster/overall status. Use for advisory items that shouldn't
    color the overall report.
    """
    name: str
    status: str
    value: Any = None
    units: str = ""
    threshold: Optional[float] = None
    baseline_value: Optional[float] = None
    baseline_deviation: Optional[float] = None
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
    host: str
    role: str
    checks: List[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        # INFO is informational and never bubbles up. Individual checks can
        # also opt out via rollup=False.
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
    name: str
    hosts: List[HostSection] = field(default_factory=list)
    cluster_checks: List[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        rollup_cluster = [c.status for c in self.cluster_checks
                          if c.rollup and c.status != STATUS_INFO]
        statuses = [h.status for h in self.hosts] + rollup_cluster
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
    cluster_name: str
    cluster_id: str
    project_name: str
    project_id: str
    timestamp: str = ""
    sections: List[Section] = field(default_factory=list)

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
    om_url: str
    generated_at: str = ""
    clusters: List[ClusterReport] = field(default_factory=list)

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


# =============================================================================
# SECTION 3: Threshold configuration
# =============================================================================
# Defaults for each metric + YAML override loading.
# -----------------------------------------------------------------------------

MODE_ABSOLUTE = "absolute"
MODE_BASELINE = "baseline"
MODE_AND = "and"
MODE_OR = "or"

DIR_ABOVE = "above"
DIR_BELOW = "below"


@dataclass(frozen=True)
class Threshold:
    red: Optional[float] = None
    warn: Optional[float] = None
    direction: str = DIR_ABOVE
    deviation: Optional[float] = None
    mode: str = MODE_ABSOLUTE


# Section 1: Connectivity & Infrastructure
SYSTEM_NETWORK_IN = Threshold(deviation=3.0, mode=MODE_BASELINE)
SYSTEM_NETWORK_OUT = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_BYTES_IN = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_BYTES_OUT = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_NUM_REQUESTS = Threshold(deviation=3.0, mode=MODE_BASELINE)

# Section 2: Compute Resources
SYSTEM_NORMALIZED_CPU_USER = Threshold(
    red=95.0, warn=80.0, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND)
SYSTEM_NORMALIZED_CPU_IOWAIT = Threshold(
    red=20.0, warn=10.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND)
PROCESS_NORMALIZED_CPU_USER = Threshold(
    red=80.0, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND)
SYSTEM_MEMORY_AVAILABLE = Threshold(
    red=500, warn=1000, direction=DIR_BELOW, deviation=0.3, mode=MODE_OR)
MEMORY_RESIDENT = Threshold(deviation=2.0, mode=MODE_BASELINE)
SWAP_USAGE_USED = Threshold(red=100, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)

# Section 3: Disk Resources
DISK_PARTITION_LATENCY_READ = Threshold(
    red=10.0, warn=5.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR)
DISK_PARTITION_LATENCY_WRITE = Threshold(
    red=10.0, warn=5.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR)
DISK_PARTITION_IOPS_READ = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_IOPS_WRITE = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_SPACE_PERCENT_FREE = Threshold(
    red=10.0, warn=20.0, direction=DIR_BELOW, mode=MODE_ABSOLUTE)

# Section 4: Cache Resources
CACHE_USED_BYTES = Threshold(deviation=2.0, mode=MODE_BASELINE)
CACHE_DIRTY_BYTES = Threshold(deviation=3.0, mode=MODE_BASELINE)
CACHE_BYTES_READ_INTO = Threshold(deviation=3.0, mode=MODE_BASELINE)
CACHE_BYTES_WRITTEN_FROM = Threshold(deviation=3.0, mode=MODE_BASELINE)

# Section 5: Database Activity & Workload
QUERY_TARGETING_SCANNED_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND)
QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND)
QUERY_EXECUTOR_SCANNED = Threshold(deviation=3.0, mode=MODE_BASELINE)
QUERY_EXECUTOR_SCANNED_OBJECTS = Threshold(deviation=3.0, mode=MODE_BASELINE)
DOCUMENT_METRICS_RETURNED = Threshold(deviation=3.0, mode=MODE_BASELINE)
DOCUMENT_METRICS_INSERTED = Threshold(deviation=3.0, mode=MODE_BASELINE)
DOCUMENT_METRICS_UPDATED = Threshold(deviation=3.0, mode=MODE_BASELINE)
DOCUMENT_METRICS_DELETED = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPERATIONS_SCAN_AND_ORDER = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_CMD = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_QUERY = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_UPDATE = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_DELETE = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_GETMORE = Threshold(deviation=3.0, mode=MODE_BASELINE)
OPCOUNTER_INSERT = Threshold(deviation=3.0, mode=MODE_BASELINE)
OP_EXECUTION_TIME_READS = Threshold(
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR)
OP_EXECUTION_TIME_WRITES = Threshold(
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR)
OP_EXECUTION_TIME_COMMANDS = Threshold(
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR)
GLOBAL_LOCK_CURRENT_QUEUE_READERS = Threshold(
    red=10, warn=5, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR)
GLOBAL_LOCK_CURRENT_QUEUE_WRITERS = Threshold(
    red=10, warn=5, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR)
GLOBAL_LOCK_CURRENT_QUEUE_TOTAL = Threshold(
    red=20, warn=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR)

# Section 6: Replication
OPLOG_REPLICATION_LAG_TIME = Threshold(
    red=60, warn=10, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
OPLOG_MASTER_TIME = Threshold(
    red=24, warn=36, direction=DIR_BELOW, mode=MODE_ABSOLUTE)
OPLOG_RATE_GB_PER_HOUR = Threshold(deviation=3.0, mode=MODE_BASELINE)

# Section 7: Connections
CONNECTIONS = Threshold(
    red=25000, warn=20000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR)


THRESHOLDS: Dict[str, Threshold] = {
    "SYSTEM_NETWORK_IN": SYSTEM_NETWORK_IN,
    "SYSTEM_NETWORK_OUT": SYSTEM_NETWORK_OUT,
    "NETWORK_BYTES_IN": NETWORK_BYTES_IN,
    "NETWORK_BYTES_OUT": NETWORK_BYTES_OUT,
    "NETWORK_NUM_REQUESTS": NETWORK_NUM_REQUESTS,
    "SYSTEM_NORMALIZED_CPU_USER": SYSTEM_NORMALIZED_CPU_USER,
    "SYSTEM_NORMALIZED_CPU_IOWAIT": SYSTEM_NORMALIZED_CPU_IOWAIT,
    "PROCESS_NORMALIZED_CPU_USER": PROCESS_NORMALIZED_CPU_USER,
    "SYSTEM_MEMORY_AVAILABLE": SYSTEM_MEMORY_AVAILABLE,
    "MEMORY_RESIDENT": MEMORY_RESIDENT,
    "SWAP_USAGE_USED": SWAP_USAGE_USED,
    "DISK_PARTITION_LATENCY_READ": DISK_PARTITION_LATENCY_READ,
    "DISK_PARTITION_LATENCY_WRITE": DISK_PARTITION_LATENCY_WRITE,
    "DISK_PARTITION_IOPS_READ": DISK_PARTITION_IOPS_READ,
    "DISK_PARTITION_IOPS_WRITE": DISK_PARTITION_IOPS_WRITE,
    "DISK_PARTITION_SPACE_PERCENT_FREE": DISK_PARTITION_SPACE_PERCENT_FREE,
    "CACHE_USED_BYTES": CACHE_USED_BYTES,
    "CACHE_DIRTY_BYTES": CACHE_DIRTY_BYTES,
    "CACHE_BYTES_READ_INTO": CACHE_BYTES_READ_INTO,
    "CACHE_BYTES_WRITTEN_FROM": CACHE_BYTES_WRITTEN_FROM,
    "QUERY_TARGETING_SCANNED_PER_RETURNED": QUERY_TARGETING_SCANNED_PER_RETURNED,
    "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED": QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED,
    "QUERY_EXECUTOR_SCANNED": QUERY_EXECUTOR_SCANNED,
    "QUERY_EXECUTOR_SCANNED_OBJECTS": QUERY_EXECUTOR_SCANNED_OBJECTS,
    "DOCUMENT_METRICS_RETURNED": DOCUMENT_METRICS_RETURNED,
    "DOCUMENT_METRICS_INSERTED": DOCUMENT_METRICS_INSERTED,
    "DOCUMENT_METRICS_UPDATED": DOCUMENT_METRICS_UPDATED,
    "DOCUMENT_METRICS_DELETED": DOCUMENT_METRICS_DELETED,
    "OPERATIONS_SCAN_AND_ORDER": OPERATIONS_SCAN_AND_ORDER,
    "OPCOUNTER_CMD": OPCOUNTER_CMD,
    "OPCOUNTER_QUERY": OPCOUNTER_QUERY,
    "OPCOUNTER_UPDATE": OPCOUNTER_UPDATE,
    "OPCOUNTER_DELETE": OPCOUNTER_DELETE,
    "OPCOUNTER_GETMORE": OPCOUNTER_GETMORE,
    "OPCOUNTER_INSERT": OPCOUNTER_INSERT,
    "OP_EXECUTION_TIME_READS": OP_EXECUTION_TIME_READS,
    "OP_EXECUTION_TIME_WRITES": OP_EXECUTION_TIME_WRITES,
    "OP_EXECUTION_TIME_COMMANDS": OP_EXECUTION_TIME_COMMANDS,
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS": GLOBAL_LOCK_CURRENT_QUEUE_READERS,
    "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS": GLOBAL_LOCK_CURRENT_QUEUE_WRITERS,
    "GLOBAL_LOCK_CURRENT_QUEUE_TOTAL": GLOBAL_LOCK_CURRENT_QUEUE_TOTAL,
    "OPLOG_REPLICATION_LAG_TIME": OPLOG_REPLICATION_LAG_TIME,
    "OPLOG_MASTER_TIME": OPLOG_MASTER_TIME,
    "OPLOG_RATE_GB_PER_HOUR": OPLOG_RATE_GB_PER_HOUR,
    "CONNECTIONS": CONNECTIONS,
}


def get_threshold(metric_name: str) -> Optional[Threshold]:
    return THRESHOLDS.get(metric_name)


def load_overrides(config_path: Optional[Union[str, Path]] = None) -> None:
    """Load threshold overrides from YAML (if PyYAML is installed).

    Lookup order:
        1. Explicit path argument
        2. OM_HEALTH_CHECK_CONFIG env var
        3. ~/.om-health-check.yaml
    """
    if not _YAML_AVAILABLE:
        return
    if config_path is None:
        config_path = os.environ.get("OM_HEALTH_CHECK_CONFIG")
    if config_path is None:
        config_path = Path.home() / ".om-health-check.yaml"
    path = Path(config_path)
    if not path.is_file():
        return
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return
    overrides = data.get("thresholds")
    if not isinstance(overrides, dict):
        return
    valid_fields = {f.name for f in fields(Threshold)}
    for metric_name, values in overrides.items():
        if metric_name not in THRESHOLDS or not isinstance(values, dict):
            continue
        default = THRESHOLDS[metric_name]
        kwargs = {f.name: getattr(default, f.name) for f in fields(Threshold)}
        for key, val in values.items():
            if key in valid_fields:
                kwargs[key] = val
        THRESHOLDS[metric_name] = Threshold(**kwargs)


# =============================================================================
# SECTION 4: Baseline fetch & evaluation
# =============================================================================
# Fetch current (1h rolling avg of PT1M samples) + baseline (PT1H, 1 week ago),
# compute deviation, and evaluate against thresholds per mode.
# -----------------------------------------------------------------------------


@dataclass
class MetricResult:
    metric_name: str
    current_value: Optional[float]
    baseline_value: Optional[float]
    deviation: Optional[float]
    status: str
    threshold: Optional[Threshold]
    message: str


def _compute_deviation(current, baseline):
    if current is None or baseline is None:
        return None
    if baseline == 0:
        return None if current == 0 else float("inf")
    return current / baseline


def _crosses_threshold(value, thresh):
    if thresh.red is None:
        return False
    if thresh.direction == DIR_BELOW:
        return value <= thresh.red
    return value >= thresh.red


def _crosses_warn(value, thresh):
    if thresh.warn is None:
        return False
    if thresh.direction == DIR_BELOW:
        return value <= thresh.warn
    return value >= thresh.warn


def _exceeds_deviation(current, baseline, thresh):
    if thresh.deviation is None or baseline is None:
        return False
    if baseline == 0:
        return current != 0
    ratio = current / baseline
    if thresh.direction == DIR_BELOW:
        return ratio <= thresh.deviation
    return ratio >= thresh.deviation


def evaluate_metric(metric_name, current_value, baseline_value) -> MetricResult:
    """Evaluate a metric against its threshold and baseline."""
    thresh = get_threshold(metric_name)
    deviation = _compute_deviation(current_value, baseline_value)

    if current_value is None:
        return MetricResult(metric_name, None, baseline_value, None,
                            STATUS_INFO, thresh, "No current data available")

    if thresh is None:
        return MetricResult(metric_name, current_value, baseline_value, deviation,
                            STATUS_GREEN, None, "No threshold configured")

    abs_red = _crosses_threshold(current_value, thresh)
    abs_warn = _crosses_warn(current_value, thresh)
    dev_red = _exceeds_deviation(current_value, baseline_value, thresh)

    baseline_missing = baseline_value is None and thresh.deviation is not None

    if thresh.mode == MODE_ABSOLUTE:
        if abs_red:
            status = STATUS_RED
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN
    elif thresh.mode == MODE_BASELINE:
        if baseline_missing:
            return MetricResult(
                metric_name, current_value, None, None, STATUS_INFO, thresh,
                f"{current_value:,.2f} — no baseline yet (cluster < 1 week old)")
        status = STATUS_RED if dev_red else STATUS_GREEN
    elif thresh.mode == MODE_AND:
        if baseline_missing:
            status = STATUS_WARN if abs_red else (STATUS_WARN if abs_warn else STATUS_GREEN)
        elif abs_red and dev_red:
            status = STATUS_RED
        elif abs_red and not dev_red:
            status = STATUS_INFO
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN
    elif thresh.mode == MODE_OR:
        if abs_red or dev_red:
            status = STATUS_RED
        elif abs_warn:
            status = STATUS_WARN
        else:
            status = STATUS_GREEN
    else:
        status = STATUS_GREEN

    message = _build_message(metric_name, current_value, baseline_value,
                             deviation, thresh, status)
    if baseline_missing and thresh.mode in (MODE_AND, MODE_OR):
        message += " (no baseline yet — cluster < 1 week old)"

    return MetricResult(metric_name, current_value, baseline_value, deviation,
                        status, thresh, message)


def _build_message(metric_name, current, baseline, deviation, thresh, status) -> str:
    parts = [f"{current:,.2f}"]
    if baseline is not None and deviation is not None:
        if deviation == float("inf"):
            parts.append("(baseline was 0)")
        else:
            parts.append(f"(baseline: {baseline:,.2f}, {deviation:.1f}x)")
    if status == STATUS_RED:
        if thresh.mode == MODE_BASELINE:
            parts.append("— significant deviation from baseline")
        elif thresh.mode == MODE_AND:
            parts.append(f"— exceeds threshold ({thresh.red}) and deviates from baseline")
        elif thresh.mode == MODE_OR:
            abs_red = _crosses_threshold(current, thresh)
            dev_red = _exceeds_deviation(current, baseline, thresh)
            if abs_red and dev_red:
                parts.append(f"— exceeds threshold ({thresh.red}) and deviates from baseline")
            elif abs_red:
                parts.append(f"— exceeds threshold ({thresh.red})")
            else:
                parts.append("— significant deviation from baseline")
        else:
            parts.append(f"— exceeds threshold ({thresh.red})")
    elif status == STATUS_INFO and thresh.mode == MODE_AND:
        parts.append(f"— above threshold ({thresh.red}) but within normal baseline range")
    elif status == STATUS_WARN:
        parts.append(f"— approaching threshold (warn: {thresh.warn})")
    return " ".join(parts)


def _baseline_time_range():
    now = datetime.now(timezone.utc)
    baseline_end = now.replace(minute=0, second=0, microsecond=0) - timedelta(weeks=1)
    baseline_start = baseline_end - timedelta(hours=1)
    return baseline_start.isoformat(), baseline_end.isoformat()


def _extract_value(measurements, metric_name):
    """Mean of non-null data points. With PT1M/PT1H this yields a 1h average."""
    for m in measurements.measurements:
        if m.name == metric_name:
            values = [dp.value for dp in m.data_points if dp.value is not None]
            if not values:
                return None
            return sum(values) / len(values)
    return None


class _FallbackMeasurements:
    """Stand-in for ProcessMeasurements when built from per-metric calls."""
    def __init__(self, measurements):
        self.measurements = measurements


_warned_metrics: set = set()


def _fetch_with_fallback(fetch_fn, metric_names, **kwargs):
    """Batched metric fetch; on failure, fall back to per-metric calls."""
    baseline_start, baseline_end = _baseline_time_range()
    try:
        current = fetch_fn(granularity="PT1M", period="PT1H",
                           metrics=metric_names, **kwargs)
    except Exception:
        current = _fetch_individually(fetch_fn, metric_names, **kwargs)
    try:
        baseline = fetch_fn(granularity="PT1H", period=None,
                            start=baseline_start, end=baseline_end,
                            metrics=metric_names, **kwargs)
    except Exception:
        baseline = _fetch_individually(fetch_fn, metric_names,
                                       start=baseline_start, end=baseline_end,
                                       **kwargs)
    return current, baseline


def _fetch_individually(fetch_fn, metric_names, start=None, end=None, **kwargs):
    all_measurements = []
    failed = []
    for name in metric_names:
        try:
            if start is not None:
                r = fetch_fn(granularity="PT1H", period=None,
                             start=start, end=end, metrics=[name], **kwargs)
            else:
                r = fetch_fn(granularity="PT1M", period="PT1H",
                             metrics=[name], **kwargs)
            all_measurements.extend(r.measurements)
        except Exception:
            failed.append(name)
    new_failures = [m for m in failed if m not in _warned_metrics]
    if new_failures:
        _warned_metrics.update(new_failures)
        print(f"Metrics unavailable: {', '.join(new_failures)}", file=sys.stderr)
    return _FallbackMeasurements(all_measurements)


def fetch_host_metrics(om, project_id, host_id, metric_names):
    current, baseline = _fetch_with_fallback(
        om.measurements.host, metric_names,
        project_id=project_id, host_id=host_id)
    return {name: (_extract_value(current, name), _extract_value(baseline, name))
            for name in metric_names}


def fetch_disk_metrics(om, project_id, host_id, partition_name, metric_names):
    current, baseline = _fetch_with_fallback(
        om.measurements.disk, metric_names,
        project_id=project_id, host_id=host_id, partition_name=partition_name)
    return {name: (_extract_value(current, name), _extract_value(baseline, name))
            for name in metric_names}


# =============================================================================
# SECTION 5: Check modules
# =============================================================================
# Each function produces one Section of the report.
# -----------------------------------------------------------------------------


# -- 5.1 Connectivity & Infrastructure ---------------------------------------

_SYSTEM_NETWORK_METRICS = ["SYSTEM_NETWORK_IN", "SYSTEM_NETWORK_OUT"]
_PROCESS_NETWORK_METRICS = ["NETWORK_BYTES_IN", "NETWORK_BYTES_OUT", "NETWORK_NUM_REQUESTS"]
# Fetch all in one batch; iterate in SYSTEM-first order to match the package.
_CONNECTIVITY_METRICS_FETCH = _PROCESS_NETWORK_METRICS + _SYSTEM_NETWORK_METRICS
_CONNECTIVITY_METRICS_ITER = _SYSTEM_NETWORK_METRICS + _PROCESS_NETWORK_METRICS

# Alerts downgraded from RED to INFO (visible, but don't color overall).
_ADVISORY_ALERT_TYPES = {
    "HOST_SECURITY_CHECKUP_NOT_MET",
}


def _check_connectivity(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Connectivity & Infrastructure")
    section.cluster_checks.append(
        Check(name="OM API reachability", status=STATUS_GREEN, message="Connected"))
    _check_alerts(client, project_id, cluster, hosts, section)
    _check_agents(client, project_id, hosts, section)

    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        if not host.host_enabled:
            hs.checks.append(Check(name="Node status", status=STATUS_RED,
                                   message="Host is disabled"))
        elif host.replica_state_name and "DOWN" in host.replica_state_name.upper():
            hs.checks.append(Check(name="Node status", status=STATUS_RED,
                                   message=f"Node state: {host.replica_state_name}"))
        else:
            hs.checks.append(Check(name="Node status", status=STATUS_GREEN,
                                   message=f"Node state: {host.replica_state_name or 'OK'}"))

        metrics = fetch_host_metrics(client.om, project_id, host.id,
                                     _CONNECTIVITY_METRICS_FETCH)
        for metric_name in _CONNECTIVITY_METRICS_ITER:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(Check(
                name=metric_name, status=result.status, value=result.current_value,
                units="bytes" if "NETWORK" in metric_name else "requests",
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
        section.hosts.append(hs)
    return section


def _check_alerts(client, project_id, cluster, hosts, section):
    alerts = client.om.alerts.list_open(project_id)
    host_ports = {h.host_port for h in hosts}
    cluster_alerts = []
    for alert in alerts:
        if alert.cluster_name and alert.cluster_name == cluster.cluster_name:
            cluster_alerts.append(alert)
        elif alert.hostname_and_port and alert.hostname_and_port in host_ports:
            cluster_alerts.append(alert)
    if cluster_alerts:
        for alert in cluster_alerts:
            is_advisory = alert.event_type_name in _ADVISORY_ALERT_TYPES
            section.cluster_checks.append(Check(
                name="Active alert",
                status=STATUS_INFO if is_advisory else STATUS_RED,
                message=(
                    f"[{alert.event_type_name}] "
                    f"{alert.hostname_and_port or alert.cluster_name or ''} — "
                    f"{alert.metric_name or alert.event_type_name} "
                    f"(since {alert.created})")))
    else:
        section.cluster_checks.append(Check(
            name="Active alerts", status=STATUS_GREEN,
            message="No open alerts for this cluster"))


def _check_agents(client, project_id, hosts, section):
    agents = client.om.agents.list_monitoring(project_id)
    host_hostnames = {h.hostname for h in hosts}
    cluster_agents = [a for a in agents if a.hostname in host_hostnames]
    if not cluster_agents:
        section.cluster_checks.append(Check(
            name="Agent status", status=STATUS_RED,
            message="No monitoring agents found for cluster hosts"))
        return
    # OM monitoring uses leader election: exactly one agent per project is
    # ACTIVE, rest are STANDBY. Missing an active agent is RED.
    active_agents = [a for a in cluster_agents if a.state_name == "ACTIVE"]
    if not active_agents:
        section.cluster_checks.append(Check(
            name="Agent status", status=STATUS_RED,
            message="No ACTIVE monitoring agent — monitoring data is not being collected"))
    else:
        active_hosts = ", ".join(a.hostname for a in active_agents)
        standby_count = len(cluster_agents) - len(active_agents)
        msg = f"Active on {active_hosts}"
        if standby_count:
            msg += f" ({standby_count} standby)"
        section.cluster_checks.append(Check(
            name="Agent status", status=STATUS_GREEN, message=msg))


# -- 5.2 Compute Resources ---------------------------------------------------

_COMPUTE_TOP_METRICS = [
    "SYSTEM_NORMALIZED_CPU_USER", "SYSTEM_NORMALIZED_CPU_IOWAIT",
    "PROCESS_NORMALIZED_CPU_USER", "SYSTEM_MEMORY_AVAILABLE",
    "MEMORY_RESIDENT", "SWAP_USAGE_USED",
]
_COMPUTE_DEEPER_CPU = [
    "SYSTEM_NORMALIZED_CPU_STEAL", "SYSTEM_NORMALIZED_CPU_GUEST",
    "SYSTEM_NORMALIZED_CPU_SOFTIRQ", "SYSTEM_NORMALIZED_CPU_IRQ",
    "SYSTEM_NORMALIZED_CPU_NICE", "SYSTEM_NORMALIZED_CPU_KERNEL",
]
_COMPUTE_DEEPER_MEM = ["SWAP_USAGE_FREE"]
_COMPUTE_UNITS = {
    "SYSTEM_NORMALIZED_CPU_USER": "%",
    "SYSTEM_NORMALIZED_CPU_IOWAIT": "%",
    "PROCESS_NORMALIZED_CPU_USER": "%",
    "SYSTEM_MEMORY_AVAILABLE": "MB",
    "MEMORY_RESIDENT": "MB",
    "SWAP_USAGE_USED": "MB",
    "SWAP_USAGE_FREE": "MB",
}


def _check_compute(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Compute Resources")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        metrics = fetch_host_metrics(client.om, project_id, host.id,
                                     _COMPUTE_TOP_METRICS)
        any_red = False
        for metric_name in _COMPUTE_TOP_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            if result.status == STATUS_RED:
                any_red = True
            hs.checks.append(Check(
                name=metric_name, status=result.status, value=result.current_value,
                units=_COMPUTE_UNITS.get(metric_name, ""),
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
        if any_red:
            deeper = fetch_host_metrics(client.om, project_id, host.id,
                                        _COMPUTE_DEEPER_CPU + _COMPUTE_DEEPER_MEM)
            for metric_name in _COMPUTE_DEEPER_CPU + _COMPUTE_DEEPER_MEM:
                current, baseline = deeper.get(metric_name, (None, None))
                if current is None:
                    continue
                dev = None
                if baseline is not None and baseline > 0:
                    dev = current / baseline
                msg = f"{current:,.2f}"
                if baseline is not None:
                    msg += f" (baseline: {baseline:,.2f})"
                hs.checks.append(Check(
                    name=metric_name, status=STATUS_INFO, value=current,
                    units=_COMPUTE_UNITS.get(metric_name, "%"),
                    baseline_value=baseline, baseline_deviation=dev, message=msg))
        section.hosts.append(hs)
    return section


# -- 5.3 Disk Resources ------------------------------------------------------

_DISK_METRICS = [
    "DISK_PARTITION_LATENCY_READ", "DISK_PARTITION_LATENCY_WRITE",
    "DISK_PARTITION_IOPS_READ", "DISK_PARTITION_IOPS_WRITE",
    "DISK_PARTITION_SPACE_PERCENT_FREE",
]
_DISK_UNITS = {
    "DISK_PARTITION_LATENCY_READ": "ms",
    "DISK_PARTITION_LATENCY_WRITE": "ms",
    "DISK_PARTITION_IOPS_READ": "IOPS",
    "DISK_PARTITION_IOPS_WRITE": "IOPS",
    "DISK_PARTITION_SPACE_PERCENT_FREE": "%",
}


def _check_disk(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Disk Resources")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        disks = client.om.deployments.list_disks(project_id, host.id)
        for disk in disks:
            metrics = fetch_disk_metrics(client.om, project_id, host.id,
                                         disk.partition_name, _DISK_METRICS)
            for metric_name in _DISK_METRICS:
                current, baseline = metrics.get(metric_name, (None, None))
                result = evaluate_metric(metric_name, current, baseline)
                hs.checks.append(Check(
                    name=f"{metric_name} [{disk.partition_name}]",
                    status=result.status, value=result.current_value,
                    units=_DISK_UNITS.get(metric_name, ""),
                    baseline_value=result.baseline_value,
                    baseline_deviation=result.deviation,
                    threshold=result.threshold.red if result.threshold else None,
                    message=result.message))
        # CPU iowait correlation
        iowait_metrics = fetch_host_metrics(
            client.om, project_id, host.id, ["SYSTEM_NORMALIZED_CPU_IOWAIT"])
        iowait_current, iowait_baseline = iowait_metrics.get(
            "SYSTEM_NORMALIZED_CPU_IOWAIT", (None, None))
        if iowait_current is not None:
            iowait_result = evaluate_metric(
                "SYSTEM_NORMALIZED_CPU_IOWAIT", iowait_current, iowait_baseline)
            disk_has_red = any(c.status == STATUS_RED for c in hs.checks)
            if disk_has_red and iowait_result.status in (STATUS_RED, STATUS_WARN):
                hs.checks.append(Check(
                    name="CPU iowait correlation", status=iowait_result.status,
                    value=iowait_current, units="%",
                    message=f"Elevated iowait ({iowait_current:.1f}%) correlates with disk pressure"))
        section.hosts.append(hs)
    return section


# -- 5.4 Cache Resources -----------------------------------------------------

_CACHE_METRICS = ["CACHE_USED_BYTES", "CACHE_DIRTY_BYTES",
                  "CACHE_BYTES_READ_INTO", "CACHE_BYTES_WRITTEN_FROM"]


def _check_cache(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Cache Resources")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        metrics = fetch_host_metrics(client.om, project_id, host.id, _CACHE_METRICS)
        for metric_name in _CACHE_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(Check(
                name=metric_name, status=result.status, value=result.current_value,
                units="bytes",
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
        section.hosts.append(hs)
    return section


# -- 5.5 Database Activity & Workload ----------------------------------------

_WORKLOAD_METRICS = [
    "QUERY_TARGETING_SCANNED_PER_RETURNED",
    "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED",
    "QUERY_EXECUTOR_SCANNED", "QUERY_EXECUTOR_SCANNED_OBJECTS",
    "DOCUMENT_METRICS_RETURNED", "DOCUMENT_METRICS_INSERTED",
    "DOCUMENT_METRICS_UPDATED", "DOCUMENT_METRICS_DELETED",
    "OPERATIONS_SCAN_AND_ORDER",
    "OPCOUNTER_CMD", "OPCOUNTER_QUERY", "OPCOUNTER_UPDATE",
    "OPCOUNTER_DELETE", "OPCOUNTER_GETMORE", "OPCOUNTER_INSERT",
    "OP_EXECUTION_TIME_READS", "OP_EXECUTION_TIME_WRITES",
    "OP_EXECUTION_TIME_COMMANDS",
    "GLOBAL_LOCK_CURRENT_QUEUE_READERS", "GLOBAL_LOCK_CURRENT_QUEUE_WRITERS",
    "GLOBAL_LOCK_CURRENT_QUEUE_TOTAL",
]
_WORKLOAD_UNITS = {
    "QUERY_TARGETING_SCANNED_PER_RETURNED": "ratio",
    "QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED": "ratio",
    "OP_EXECUTION_TIME_READS": "ms",
    "OP_EXECUTION_TIME_WRITES": "ms",
    "OP_EXECUTION_TIME_COMMANDS": "ms",
}


def _check_workload(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Database Activity & Workload")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        metrics = fetch_host_metrics(client.om, project_id, host.id, _WORKLOAD_METRICS)
        for metric_name in _WORKLOAD_METRICS:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(Check(
                name=metric_name, status=result.status, value=result.current_value,
                units=_WORKLOAD_UNITS.get(metric_name, "ops/s"),
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
        _check_performance_advisor(client, project_id, host, hs)
        section.hosts.append(hs)
    return section


def _check_performance_advisor(client, project_id, host, hs):
    host_id = host.host_port
    now_ms = int(time.time() * 1000)
    one_hour_ms = 60 * 60 * 1000
    try:
        slow_queries = client.om.performance_advisor.get_slow_queries(
            project_id=project_id, host_id=host_id,
            since=now_ms - one_hour_ms, duration=one_hour_ms)
        advisor_response = client.om.performance_advisor.get_suggested_indexes(
            project_id=project_id, host_id=host_id,
            since=now_ms - one_hour_ms, duration=one_hour_ms)
        suggested_indexes = advisor_response.get("suggested_indexes", [])
    except Exception:
        hs.checks.append(Check(name="Performance Advisor", status=STATUS_INFO,
                               message="Performance Advisor data unavailable"))
        return
    has_slow = bool(slow_queries)
    has_suggestions = bool(suggested_indexes)
    if has_suggestions:
        namespaces = {idx.namespace for idx in suggested_indexes}
        hs.checks.append(Check(
            name="Performance Advisor — suggested indexes", status=STATUS_RED,
            value=len(suggested_indexes),
            message=f"{len(suggested_indexes)} index suggestion(s) for: "
                    + ", ".join(sorted(namespaces))))
    elif has_slow:
        hs.checks.append(Check(
            name="Performance Advisor — slow queries", status=STATUS_RED,
            value=len(slow_queries),
            message=f"{len(slow_queries)} slow query log(s) in last hour"))
    else:
        hs.checks.append(Check(name="Performance Advisor", status=STATUS_GREEN,
                               message="No slow queries or index suggestions"))


# -- 5.6 Replication ---------------------------------------------------------

_REPL_SECONDARY_METRICS = ["OPLOG_REPLICATION_LAG_TIME"]
_REPL_PRIMARY_METRICS = ["OPLOG_MASTER_TIME", "OPLOG_RATE_GB_PER_HOUR"]
_REPL_UNITS = {
    "OPLOG_REPLICATION_LAG_TIME": "seconds",
    "OPLOG_MASTER_TIME": "hours",
    "OPLOG_RATE_GB_PER_HOUR": "GB/hr",
}


def _check_replication(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Replication")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        if host.is_primary:
            metric_names = _REPL_PRIMARY_METRICS
        elif host.is_secondary:
            metric_names = _REPL_SECONDARY_METRICS + _REPL_PRIMARY_METRICS
        else:
            continue  # skip arbiters and mongos
        metrics = fetch_host_metrics(client.om, project_id, host.id, metric_names)
        for metric_name in metric_names:
            current, baseline = metrics.get(metric_name, (None, None))
            result = evaluate_metric(metric_name, current, baseline)
            hs.checks.append(Check(
                name=metric_name, status=result.status, value=result.current_value,
                units=_REPL_UNITS.get(metric_name, ""),
                baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
        section.hosts.append(hs)
    return section


# -- 5.7 Connections ---------------------------------------------------------

_CONN_METRICS = ["CONNECTIONS"]
_LATENCY_METRICS = ["OP_EXECUTION_TIME_READS", "OP_EXECUTION_TIME_WRITES"]


def _check_connections(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Connections")
    for host in hosts:
        hs = HostSection(host=host.host_port,
                         role=host.replica_state_name or host.type_name or "UNKNOWN")
        metrics = fetch_host_metrics(client.om, project_id, host.id,
                                     _CONN_METRICS + _LATENCY_METRICS)
        conn_current, conn_baseline = metrics.get("CONNECTIONS", (None, None))
        if conn_current is not None and conn_current == 0:
            hs.checks.append(Check(
                name="CONNECTIONS", status=STATUS_GREEN, value=0,
                units="connections", baseline_value=conn_baseline,
                message="0 connections — MongoDB is healthy. "
                        "Problem is upstream (load balancer, DNS, app config)."))
        else:
            result = evaluate_metric("CONNECTIONS", conn_current, conn_baseline)
            hs.checks.append(Check(
                name="CONNECTIONS", status=result.status, value=result.current_value,
                units="connections", baseline_value=result.baseline_value,
                baseline_deviation=result.deviation,
                threshold=result.threshold.red if result.threshold else None,
                message=result.message))
            if result.status == STATUS_RED and conn_current is not None:
                latency_elevated = False
                for metric_name in _LATENCY_METRICS:
                    cur, base = metrics.get(metric_name, (None, None))
                    if cur is not None:
                        r = evaluate_metric(metric_name, cur, base)
                        if r.status in (STATUS_RED, STATUS_WARN):
                            latency_elevated = True
                            break
                if latency_elevated:
                    hs.checks.append(Check(
                        name="Connection storm correlation", status=STATUS_INFO,
                        message="Connection spike correlates with elevated "
                                "operation latency — connection storm may be a "
                                "symptom, not the root cause."))
        section.hosts.append(hs)
    return section


# -- 5.8 Backup --------------------------------------------------------------

def _check_backup(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Backup")
    try:
        config = client.om.backup.get_backup_config(project_id, cluster.id)
    except Exception:
        section.cluster_checks.append(Check(
            name="Backup configuration", status=STATUS_INFO,
            message="Backup configuration not available for this cluster"))
        return section
    if config.status_name != "STARTED":
        section.cluster_checks.append(Check(
            name="Backup configuration", status=STATUS_INFO,
            message=f"Backup status: {config.status_name}"))
        return section
    section.cluster_checks.append(Check(
        name="Backup configuration", status=STATUS_GREEN,
        message="Backup is enabled and active"))

    try:
        schedule = client.om.backup.get_snapshot_schedule(project_id, cluster.id)
        snapshots = client.om.backup.list_snapshots(project_id, cluster.id)
    except Exception as exc:
        section.cluster_checks.append(Check(
            name="Backup capture lag", status=STATUS_INFO,
            message=f"Could not retrieve snapshot data: {exc}"))
        return section
    if not snapshots:
        section.cluster_checks.append(Check(
            name="Backup capture lag", status=STATUS_RED,
            message="No snapshots found — backup may not be capturing"))
        return section
    latest = snapshots[0]
    if not latest.complete:
        section.cluster_checks.append(Check(
            name="Snapshot in progress", status=STATUS_INFO,
            message="A snapshot is currently being captured"))
        if latest.parts:
            for part in latest.parts:
                if part.replica_state:
                    section.cluster_checks.append(Check(
                        name="Snapshot source", status=STATUS_INFO,
                        message=f"Replica set {part.replica_set_name}: "
                                f"snapshot from {part.replica_state}"))
    if latest.created and isinstance(latest.created, dict):
        created_str = latest.created.get("date", "")
        if created_str:
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hours_since = (now - created_dt).total_seconds() / 3600
                expected_interval = schedule.snapshot_interval_hours
                overdue_threshold = expected_interval * 1.5
                if hours_since > overdue_threshold:
                    section.cluster_checks.append(Check(
                        name="Backup capture lag", status=STATUS_RED,
                        value=round(hours_since, 1), units="hours",
                        message=f"Latest snapshot is {hours_since:.1f}h old "
                                f"(expected every {expected_interval}h) — "
                                "snapshot may be delayed"))
                else:
                    section.cluster_checks.append(Check(
                        name="Backup capture lag", status=STATUS_GREEN,
                        value=round(hours_since, 1), units="hours",
                        message=f"Latest snapshot is {hours_since:.1f}h old "
                                f"(expected every {expected_interval}h)"))
            except (ValueError, TypeError):
                section.cluster_checks.append(Check(
                    name="Backup capture lag", status=STATUS_INFO,
                    message=f"Could not parse snapshot timestamp: {created_str}"))
    return section


# -- 5.9 Version Information -------------------------------------------------

# Minimum MongoDB 7.0+ versions considered safe (CVE coverage).
MINIMUM_SAFE_VERSIONS = {
    "7.0": "7.0.29",
    "8.0": "8.0.18",
    "8.2": "8.2.4",
}


def _check_version(client, project_id, cluster, hosts) -> Section:
    section = Section(name="Version Information")
    versions = {h.version for h in hosts if h.version}
    if not versions:
        section.cluster_checks.append(Check(
            name="Version consistency", status=STATUS_INFO,
            message="No version data available"))
        return section
    if len(versions) == 1:
        ver = next(iter(versions))
        section.cluster_checks.append(Check(
            name="Version consistency", status=STATUS_GREEN,
            message=f"All {len(hosts)} nodes running {ver}"))
    else:
        section.cluster_checks.append(Check(
            name="Version consistency", status=STATUS_RED,
            message=f"Mixed versions: {', '.join(sorted(versions))}"))

    for ver in sorted(versions):
        try:
            parsed = Version(ver)
        except InvalidVersion:
            section.cluster_checks.append(Check(
                name="Known-bad version", status=STATUS_INFO,
                message=f"Could not parse version: {ver}"))
            continue
        major_minor = f"{parsed.major}.{parsed.minor}"
        min_safe = MINIMUM_SAFE_VERSIONS.get(major_minor)
        if not min_safe:
            section.cluster_checks.append(Check(
                name="Known-bad version", status=STATUS_INFO,
                message=f"{ver} — no known-bad version data for {major_minor}"))
            continue
        if parsed < Version(min_safe):
            section.cluster_checks.append(Check(
                name="Known-bad version", status=STATUS_RED,
                message=f"{ver} is below minimum safe version ({min_safe}) — "
                        "upgrade recommended for CVE coverage"))
        else:
            section.cluster_checks.append(Check(
                name="Known-bad version", status=STATUS_GREEN,
                message=f"{ver} meets minimum safe version ({min_safe})"))
    return section


# =============================================================================
# SECTION 6: Renderers
# =============================================================================
# Convert a Report into txt / json / html output.
# -----------------------------------------------------------------------------


# -- 6.1 Text renderer -------------------------------------------------------

def _render_txt(report: Report) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("OM HEALTH CHECK REPORT")
    lines.append(f"Generated: {report.generated_at}")
    lines.append(f"Ops Manager: {report.om_url}")
    lines.append(f"Overall: [{report.overall_status}]")
    lines.append("=" * 72)

    for cr in report.clusters:
        lines.append("")
        lines.append("-" * 72)
        lines.append(f"Cluster: {cr.cluster_name}  |  Project: {cr.project_name}  |  "
                     f"[{cr.overall_status}]")
        lines.append("-" * 72)
        for section in cr.sections:
            lines.append("")
            lines.append(f"  ## {section.name}  [{section.status}]")
            for check in section.cluster_checks:
                lines.append(_format_check_txt(check, indent=4))
            for hs in section.hosts:
                lines.append(f"    -- {hs.host} ({hs.role})")
                for check in hs.checks:
                    lines.append(_format_check_txt(check, indent=6))
        lines.append("")
        red, green, info, warn = _count_statuses(cr)
        lines.append(f"  Summary: {red} RED, {warn} WARN, {info} INFO, {green} GREEN")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def _format_check_txt(check: Check, indent: int) -> str:
    pad = " " * indent
    status_tag = f"[{check.status}]"
    parts = [f"{pad}{status_tag:7s} {check.name}"]
    if check.message:
        parts.append(f" — {check.message}")
    return "".join(parts)


def _count_statuses(cr: ClusterReport):
    red = green = info = warn = 0
    for section in cr.sections:
        for check in section.cluster_checks:
            if check.status == STATUS_RED: red += 1
            elif check.status == STATUS_GREEN: green += 1
            elif check.status == STATUS_WARN: warn += 1
            else: info += 1
        for hs in section.hosts:
            for check in hs.checks:
                if check.status == STATUS_RED: red += 1
                elif check.status == STATUS_GREEN: green += 1
                elif check.status == STATUS_WARN: warn += 1
                else: info += 1
    return red, green, info, warn


# -- 6.2 JSON renderer -------------------------------------------------------

def _render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2)


# -- 6.3 HTML renderer -------------------------------------------------------

_HTML_ENV = Environment(autoescape=True)
_HTML_TEMPLATE = _HTML_ENV.from_string("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OM Health Check Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #f5f5f5; color: #333; padding: 20px; }
  .report-header { background: #1a1a2e; color: #fff; padding: 20px; border-radius: 8px;
                   margin-bottom: 20px; }
  .report-header h1 { font-size: 1.4em; margin-bottom: 8px; }
  .report-header .meta { font-size: 0.85em; color: #aaa; }
  .cluster { background: #fff; border-radius: 8px; margin-bottom: 20px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
  .cluster-header { padding: 16px 20px; border-bottom: 1px solid #eee;
                    display: flex; justify-content: space-between; align-items: center; }
  .cluster-header h2 { font-size: 1.1em; }
  .section { border-bottom: 1px solid #f0f0f0; }
  .section-header { padding: 12px 20px; background: #fafafa; cursor: pointer;
                    display: flex; justify-content: space-between; align-items: center;
                    font-weight: 600; font-size: 0.95em; }
  .section-header:hover { background: #f0f0f0; }
  .section-body { padding: 0 20px 12px; }
  .host-group { margin: 8px 0; }
  .host-label { font-size: 0.85em; color: #666; padding: 4px 0; font-weight: 600; }
  .check { display: flex; align-items: baseline; padding: 3px 0; font-size: 0.85em; }
  .check .badge { display: inline-block; width: 52px; text-align: center; font-size: 0.75em;
                  font-weight: 700; padding: 2px 6px; border-radius: 3px; margin-right: 8px;
                  flex-shrink: 0; }
  .check .name { font-weight: 600; margin-right: 6px; white-space: nowrap; }
  .check .msg { color: #555; }
  .badge.RED { background: #fee; color: #c0392b; }
  .badge.GREEN { background: #eafaf1; color: #27ae60; }
  .badge.WARN { background: #fef9e7; color: #f39c12; }
  .badge.INFO { background: #eaf2f8; color: #2980b9; }
  .status-pill { font-size: 0.8em; font-weight: 700; padding: 3px 10px;
                 border-radius: 12px; }
  .status-pill.RED { background: #c0392b; color: #fff; }
  .status-pill.GREEN { background: #27ae60; color: #fff; }
  .status-pill.WARN { background: #f39c12; color: #fff; }
  .status-pill.INFO { background: #2980b9; color: #fff; }
  details > summary { list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
  details[open] .arrow { transform: rotate(90deg); }
  .arrow { display: inline-block; transition: transform 0.15s; margin-right: 6px; }
</style>
</head>
<body>
<div class="report-header">
  <h1>OM Health Check Report</h1>
  <div class="meta">
    Generated: {{ report.generated_at }} &nbsp;|&nbsp;
    Ops Manager: {{ report.om_url }} &nbsp;|&nbsp;
    Overall: <span class="status-pill {{ report.overall_status }}">{{ report.overall_status }}</span>
  </div>
</div>

{% for cr in report.clusters %}
<div class="cluster">
  <div class="cluster-header">
    <h2>{{ cr.cluster_name }} &mdash; {{ cr.project_name }}</h2>
    <span class="status-pill {{ cr.overall_status }}">{{ cr.overall_status }}</span>
  </div>

  {% for section in cr.sections %}
  <div class="section">
    <details{% if section.status == 'RED' %} open{% endif %}>
      <summary class="section-header">
        <span><span class="arrow">&#9654;</span> {{ section.name }}</span>
        <span class="status-pill {{ section.status }}">{{ section.status }}</span>
      </summary>
      <div class="section-body">
        {% for check in section.cluster_checks %}
        <div class="check">
          <span class="badge {{ check.status }}">{{ check.status }}</span>
          <span class="name">{{ check.name }}</span>
          <span class="msg">{{ check.message }}</span>
        </div>
        {% endfor %}

        {% for hs in section.hosts %}
        <div class="host-group">
          <div class="host-label">{{ hs.host }} ({{ hs.role }})</div>
          {% for check in hs.checks %}
          <div class="check">
            <span class="badge {{ check.status }}">{{ check.status }}</span>
            <span class="name">{{ check.name }}</span>
            <span class="msg">{{ check.message }}</span>
          </div>
          {% endfor %}
        </div>
        {% endfor %}
      </div>
    </details>
  </div>
  {% endfor %}
</div>
{% endfor %}

</body>
</html>
""")


def _render_html(report: Report) -> str:
    return _HTML_TEMPLATE.render(report=report)


_RENDERERS = {
    "txt": _render_txt,
    "json": _render_json,
    "html": _render_html,
}


# =============================================================================
# SECTION 7: Runner + CLI
# =============================================================================


@dataclass(frozen=True)
class Config:
    om_url: str
    username: str
    api_key: str
    project_names: List[str]
    cluster_name: Optional[str] = None
    formats: Optional[List[str]] = None

    def __post_init__(self):
        if self.formats is None:
            object.__setattr__(self, "formats", ["txt"])


class HealthCheckClient:
    """Wraps OpsManagerClient with convenience helpers for project/cluster/host."""

    def __init__(self, config: Config):
        self.om = OpsManagerClient(
            base_url=config.om_url,
            public_key=config.username,
            private_key=config.api_key,
        )

    def close(self):
        self.om.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def resolve_project(self, project_name: str) -> Project:
        return self.om.projects.get_by_name(project_name)

    def get_clusters(self, project_id: str,
                     cluster_name: Optional[str] = None) -> List[Cluster]:
        clusters = self.om.clusters.list(project_id)
        if cluster_name:
            clusters = [c for c in clusters if c.cluster_name == cluster_name]
            if not clusters:
                raise ValueError(
                    f"Cluster '{cluster_name}' not found in project {project_id}")
        return clusters

    def get_hosts_for_cluster(self, project_id: str,
                              cluster_id: str) -> List[Host]:
        return self.om.deployments.list_hosts(project_id, cluster_id=cluster_id)


_CHECK_SECTIONS = [
    ("Connectivity & Infrastructure", _check_connectivity),
    ("Compute Resources", _check_compute),
    ("Disk Resources", _check_disk),
    ("Cache Resources", _check_cache),
    ("Database Activity & Workload", _check_workload),
    ("Replication", _check_replication),
    ("Connections", _check_connections),
    ("Backup", _check_backup),
    ("Version Information", _check_version),
]

_PERMISSION_HINT = (
    "The API key requires the Project Read Only role. "
    "See: https://www.mongodb.com/docs/ops-manager/current/reference/user-roles/"
)


def run(config: Config) -> Report:
    _warned_metrics.clear()
    report = Report(om_url=config.om_url)

    try:
        client = HealthCheckClient(config)
    except Exception as exc:
        message = f"Failed to connect: {exc}"
        if isinstance(exc, OpsManagerAuthenticationError):
            message = f"Authentication failed — check OPS_MANAGER_USER and OPS_MANAGER_API_KEY. {exc}"
        elif isinstance(exc, OpsManagerForbiddenError):
            message = f"Access denied. {_PERMISSION_HINT} ({exc})"
        cr = ClusterReport(cluster_name="N/A", cluster_id="N/A",
                           project_name=", ".join(config.project_names),
                           project_id="N/A")
        cr.sections.append(Section(
            name="Connectivity & Infrastructure",
            cluster_checks=[Check(name="OM API reachability", status=STATUS_RED,
                                  message=message)]))
        report.clusters.append(cr)
        _render_report(report, config)
        return report

    with client:
        for project_name in config.project_names:
            try:
                project = client.resolve_project(project_name)
            except (OpsManagerAuthenticationError, OpsManagerForbiddenError):
                cr = ClusterReport(cluster_name="N/A", cluster_id="N/A",
                                   project_name=project_name, project_id="N/A")
                cr.sections.append(Section(
                    name="Connectivity & Infrastructure",
                    cluster_checks=[Check(name="Project resolution", status=STATUS_RED,
                                          message=f"Permission denied for project '{project_name}'. {_PERMISSION_HINT}")]))
                report.clusters.append(cr)
                continue
            except Exception as exc:
                cr = ClusterReport(cluster_name="N/A", cluster_id="N/A",
                                   project_name=project_name, project_id="N/A")
                cr.sections.append(Section(
                    name="Connectivity & Infrastructure",
                    cluster_checks=[Check(name="Project resolution", status=STATUS_RED,
                                          message=f"Failed to resolve project '{project_name}': {exc}")]))
                report.clusters.append(cr)
                continue

            try:
                clusters = client.get_clusters(project.id, config.cluster_name)
            except Exception as exc:
                cr = ClusterReport(cluster_name=config.cluster_name or "N/A",
                                   cluster_id="N/A", project_name=project.name,
                                   project_id=project.id)
                cr.sections.append(Section(
                    name="Connectivity & Infrastructure",
                    cluster_checks=[Check(name="Cluster resolution", status=STATUS_RED,
                                          message=f"Failed to list clusters: {exc}")]))
                report.clusters.append(cr)
                continue

            for cluster in clusters:
                report.clusters.append(_check_cluster(client, project, cluster))

    _render_report(report, config)
    return report


def _check_cluster(client, project, cluster) -> ClusterReport:
    try:
        hosts = client.get_hosts_for_cluster(project.id, cluster.id)
    except Exception as exc:
        cr = ClusterReport(cluster_name=cluster.cluster_name, cluster_id=cluster.id,
                           project_name=project.name, project_id=project.id)
        cr.sections.append(Section(
            name="Connectivity & Infrastructure",
            cluster_checks=[Check(name="Host discovery", status=STATUS_RED,
                                  message=f"Failed to list hosts: {exc}")]))
        return cr

    cr = ClusterReport(cluster_name=cluster.cluster_name, cluster_id=cluster.id,
                       project_name=project.name, project_id=project.id)
    for section_name, check_fn in _CHECK_SECTIONS:
        try:
            section = check_fn(client, project.id, cluster, hosts)
            cr.sections.append(section)
        except (OpsManagerAuthenticationError, OpsManagerForbiddenError):
            cr.sections.append(Section(
                name=section_name,
                cluster_checks=[Check(name=section_name, status=STATUS_RED,
                                      message=f"Permission denied for {section_name}. {_PERMISSION_HINT}")]))
        except Exception as exc:
            cr.sections.append(Section(
                name=section_name,
                cluster_checks=[Check(name=section_name, status=STATUS_RED,
                                      message=f"Check failed: {exc}")]))
    return cr


def _render_report(report, config):
    if len(config.formats) == 1:
        renderer = _RENDERERS.get(config.formats[0])
        if renderer:
            print(renderer(report))
        return
    for fmt in config.formats:
        renderer = _RENDERERS.get(fmt)
        if renderer:
            filename = f"om-health-check-report.{fmt}"
            with open(filename, "w") as f:
                f.write(renderer(report))
            print(f"Wrote {filename}", file=sys.stderr)


_VALID_FORMATS = {"txt", "json", "html"}


def _parse_formats(value):
    formats = [f.strip().lower() for f in value.split(",")]
    invalid = set(formats) - _VALID_FORMATS
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Invalid format(s): {', '.join(sorted(invalid))}. "
            f"Valid formats: {', '.join(sorted(_VALID_FORMATS))}")
    return formats


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="om-health-check",
        description=f"MongoDB Ops Manager automated health check tool (standalone v{__version__})",
    )
    parser.add_argument("--om-url", required=True, help="Ops Manager base URL")
    parser.add_argument("--project", action="append", required=True, dest="projects",
                        help="Project name (repeatable)")
    parser.add_argument("--cluster", default=None,
                        help="Cluster name filter (omit to check all clusters)")
    parser.add_argument("--format", default="txt", type=_parse_formats, dest="formats",
                        help="Output format: txt, json, html, or comma-separated (default: txt)")
    parser.add_argument("--config", default=None,
                        help="Path to YAML config file for threshold overrides")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    username = os.environ.get("OPS_MANAGER_USER")
    api_key = os.environ.get("OPS_MANAGER_API_KEY")
    if not username or not api_key:
        print("Error: OPS_MANAGER_USER and OPS_MANAGER_API_KEY environment "
              "variables must be set.", file=sys.stderr)
        return 1

    load_overrides(args.config)

    config = Config(
        om_url=args.om_url, username=username, api_key=api_key,
        project_names=args.projects, cluster_name=args.cluster,
        formats=args.formats,
    )
    try:
        run(config)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
