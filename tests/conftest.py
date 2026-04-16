"""Shared test fixtures — mock client, sample hosts, clusters."""

from __future__ import annotations
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from opsmanager.types import Alert, Agent, Cluster, Host, Snapshot, SnapshotPart, BackupConfig, SnapshotSchedule, Disk


def make_host(
    host_id="h1",
    hostname="mongo1.example.com",
    port=27017,
    replica_state_name="PRIMARY",
    host_enabled=True,
    version="7.0.31",
    cluster_id="c1",
    type_name="REPLICA_PRIMARY",
) -> Host:
    h = MagicMock(spec=Host)
    h.id = host_id
    h.hostname = hostname
    h.port = port
    h.host_port = f"{hostname}:{port}"
    h.replica_state_name = replica_state_name
    h.host_enabled = host_enabled
    h.version = version
    h.cluster_id = cluster_id
    h.type_name = type_name
    h.is_primary = replica_state_name == "PRIMARY"
    h.is_secondary = replica_state_name == "SECONDARY"
    h.is_arbiter = replica_state_name == "ARBITER"
    h.is_mongos = type_name == "MONGOS"
    return h


def make_cluster(cluster_id="c1", cluster_name="myReplicaSet") -> Cluster:
    c = MagicMock(spec=Cluster)
    c.id = cluster_id
    c.cluster_name = cluster_name
    return c


def make_alert(
    alert_id="a1",
    event_type="HOST_DOWN",
    hostname_and_port="mongo1.example.com:27017",
    cluster_name=None,
    metric_name=None,
    created="2026-04-01T00:00:00Z",
) -> Alert:
    a = MagicMock(spec=Alert)
    a.id = alert_id
    a.event_type_name = event_type
    a.hostname_and_port = hostname_and_port
    a.cluster_name = cluster_name
    a.metric_name = metric_name
    a.created = created
    return a


def make_agent(hostname="mongo1.example.com", state_name="ACTIVE", last_ping=None) -> Agent:
    a = MagicMock(spec=Agent)
    a.hostname = hostname
    a.state_name = state_name
    a.last_ping = last_ping
    return a


def make_disk(partition_name="nvme1n1") -> Disk:
    d = MagicMock(spec=Disk)
    d.partition_name = partition_name
    return d


@pytest.fixture
def primary():
    return make_host()


@pytest.fixture
def secondary():
    return make_host(
        host_id="h2",
        hostname="mongo2.example.com",
        replica_state_name="SECONDARY",
        type_name="REPLICA_SECONDARY",
    )


@pytest.fixture
def three_hosts(primary, secondary):
    third = make_host(
        host_id="h3",
        hostname="mongo3.example.com",
        replica_state_name="SECONDARY",
        type_name="REPLICA_SECONDARY",
    )
    return [primary, secondary, third]


@pytest.fixture
def cluster():
    return make_cluster()


@pytest.fixture
def mock_client():
    """A mock HealthCheckClient with stubbed OM services."""
    client = MagicMock()
    client.om = MagicMock()
    client.om.alerts.list_open.return_value = []
    client.om.agents.list_monitoring.return_value = []
    client.om.deployments.list_disks.return_value = []
    client.om.backup.get_backup_config.side_effect = Exception("not configured")
    return client


def make_sample_report():
    """Shared sample report for renderer tests."""
    from om_health_check.models import (
        Report, ClusterReport, Section, HostSection, Check,
        STATUS_GREEN, STATUS_RED, STATUS_WARN,
    )
    r = Report(om_url="https://om.example.com")
    cr = ClusterReport(
        cluster_name="rs0", cluster_id="c1",
        project_name="Prod", project_id="p1",
    )

    s1 = Section(name="Connectivity & Infrastructure")
    s1.cluster_checks.append(Check(name="OM API reachability", status=STATUS_GREEN, message="Connected"))
    s1.cluster_checks.append(Check(name="Active alert", status=STATUS_RED, message="HOST_DOWN"))
    hs1 = HostSection(host="mongo1:27017", role="PRIMARY")
    hs1.checks.append(Check(name="Node status", status=STATUS_GREEN, message="PRIMARY"))
    s1.hosts.append(hs1)
    cr.sections.append(s1)

    s2 = Section(name="Cache Resources")
    hs2 = HostSection(host="mongo1:27017", role="PRIMARY")
    hs2.checks.append(Check(name="CACHE_USED_BYTES", status=STATUS_WARN, value=82.0, message="approaching"))
    s2.hosts.append(hs2)
    cr.sections.append(s2)

    s3 = Section(name="Connections")
    hs3 = HostSection(host="mongo1:27017", role="PRIMARY")
    hs3.checks.append(Check(
        name="CONNECTIONS", status=STATUS_RED, value=26000,
        units="connections", threshold=25000, baseline_value=10000,
        baseline_deviation=2.6, message="exceeds threshold",
    ))
    s3.hosts.append(hs3)
    cr.sections.append(s3)

    r.clusters.append(cr)
    return r
