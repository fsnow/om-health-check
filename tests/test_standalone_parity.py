"""Byte-strict parity between the package txt renderer and the standalone.

Why this test exists: the standalone is hand-mirrored from the package, and
in 2026-06-23 review the user asked for a hard guarantee that they hadn't
drifted. Live runs don't prove parity because metric values shift between
the two sequential script invocations; this test feeds both renderers
identical synthesized data and checks the output is byte-identical.

If this test fails after a renderer change, either the standalone was
not updated to match the package, or vice versa. Fix the lagging side.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from om_health_check.models import (
    Check as PkgCheck,
    ClusterReport as PkgClusterReport,
    HostSection as PkgHostSection,
    Report as PkgReport,
    Section as PkgSection,
    Topology as PkgTopology,
)
from om_health_check.renderers.txt import render as pkg_render

STANDALONE_PATH = Path(__file__).resolve().parent.parent / "om-health-check-standalone.py"


@pytest.fixture(scope="module")
def standalone():
    spec = importlib.util.spec_from_file_location("standalone", str(STANDALONE_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["standalone"] = mod  # dataclasses needs the module in sys.modules
    spec.loader.exec_module(mod)
    return mod


def _build_report(mod, Report, ClusterReport, Topology, Section, HostSection, Check):
    """Construct an identical report in either module's namespace."""
    r = Report(om_url="https://om.example.com")
    r.started_at = "2026-06-23T15:00:00+00:00"
    r.finished_at = "2026-06-23T15:01:00+00:00"

    cr = ClusterReport(
        cluster_name="rs0", cluster_id="c1",
        project_name="ProjA", project_id="p1",
        timestamp="2026-06-23T15:00:00+00:00",
        topology=Topology(
            node_count=3, cluster_type="REPLICA_SET",
            role_counts={"PRIMARY": 1, "SECONDARY": 2}, shard_count=0,
        ),
    )

    # Section with a cluster-level check
    sec_conn = Section(name="Connectivity & Infrastructure")
    sec_conn.cluster_checks.append(Check(
        name="Agent status", status="GREEN",
        message="Active on m1.example.com (2 standby)",
    ))
    cr.sections.append(sec_conn)

    # Section with per-host checks (multiple statuses)
    sec_compute = Section(name="Compute Resources")
    primary = HostSection(host="m1.example.com:27017", role="PRIMARY")
    primary.checks.append(Check(
        name="MEMORY_RESIDENT", status="GREEN", value=500.0,
        message="500.00 (baseline: 480.00, 1.0x)",
    ))
    primary.checks.append(Check(
        name="SWAP_USAGE_USED", status="RED", value=200.0,
        message="200.00 — exceeds threshold (100)",
    ))
    sec_compute.hosts.append(primary)

    secondary = HostSection(host="m2.example.com:27017", role="SECONDARY")
    secondary.checks.append(Check(
        name="MEMORY_RESIDENT", status="GREEN", value=510.0,
        message="510.00 (baseline: 482.00, 1.1x)",
    ))
    sec_compute.hosts.append(secondary)
    cr.sections.append(sec_compute)

    # Sharded section structure: topology variant
    cr2 = ClusterReport(
        cluster_name="shardedCluster", cluster_id="c2",
        project_name="ProjB", project_id="p2",
        timestamp="2026-06-23T15:00:00+00:00",
        topology=Topology(
            node_count=15, cluster_type="SHARDED_REPLICA_SET",
            role_counts={"SECONDARY": 6, "SHARD_MONGOS": 6, "PRIMARY": 3},
            shard_count=2,
        ),
    )
    sec_oplog = Section(name="Oplog")
    sh_primary = HostSection(host="shard0_a:27017", role="PRIMARY")
    sh_primary.checks.append(Check(
        name="OPLOG_MASTER_TIME", status="GREEN", value=168.5, units="hours",
        message="168.50 (baseline: 170.00, 1.0x)",
    ))
    sec_oplog.hosts.append(sh_primary)
    cr2.sections.append(sec_oplog)

    r.clusters.append(cr)
    r.clusters.append(cr2)
    return r


def test_renderer_parity_full_report(standalone):
    pkg_r = _build_report(
        None, PkgReport, PkgClusterReport, PkgTopology,
        PkgSection, PkgHostSection, PkgCheck,
    )
    std_r = _build_report(
        standalone, standalone.Report, standalone.ClusterReport, standalone.Topology,
        standalone.Section, standalone.HostSection, standalone.Check,
    )

    pkg_out = pkg_render(pkg_r)
    std_out = standalone._render_txt(std_r)

    if pkg_out != std_out:
        import difflib
        diff = "\n".join(difflib.unified_diff(
            pkg_out.splitlines(), std_out.splitlines(),
            lineterm="", fromfile="pkg", tofile="standalone",
        ))
        pytest.fail(
            f"Renderer output diverged ({len(pkg_out)} vs {len(std_out)} bytes):\n{diff}"
        )


def test_threshold_metric_names_match(standalone):
    """All metric names registered in the package's THRESHOLDS dict should also
    exist in the standalone's THRESHOLDS dict (and vice versa). Catches typos
    where a metric was added in one but not the other."""
    from om_health_check.thresholds import THRESHOLDS as pkg_thresholds
    pkg_names = set(pkg_thresholds.keys())
    std_names = set(standalone.THRESHOLDS.keys())
    only_pkg = pkg_names - std_names
    only_std = std_names - pkg_names
    if only_pkg or only_std:
        pytest.fail(
            f"Threshold name mismatch:\n  only in pkg: {sorted(only_pkg)}\n"
            f"  only in standalone: {sorted(only_std)}"
        )
