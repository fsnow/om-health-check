"""Section 9: Version Information checks."""

from __future__ import annotations

from packaging.version import Version, InvalidVersion

from opsmanager.types import Cluster, Host

from om_health_check.client import HealthCheckClient
from om_health_check.models import STATUS_GREEN, STATUS_RED, Check, Section

# Minimum safe versions — below these have known CVEs or critical bugs.
# Key is "major.minor", value is minimum safe patch version.
MINIMUM_SAFE_VERSIONS = {
    "7.0": "7.0.29",
    "8.0": "8.0.18",
    "8.2": "8.2.4",
}

# Reasons for the minimum versions
VERSION_ISSUES = (
    "CVE-2026-25613 (CVSS 7.1, query planner segfault), "
    "CVE-2026-1849/1850 (CVSS 7.1, OOM/DoS), "
    "SERVER-94315 (duplicate records in sharded queries)"
)


def run(
    client: HealthCheckClient,
    project_id: str,
    cluster: Cluster,
    hosts: list[Host],
) -> Section:
    section = Section(name="Version Information")

    # Collect versions across all hosts
    versions: dict[str, list[str]] = {}  # version -> list of host:port
    for host in hosts:
        v = host.version or "unknown"
        versions.setdefault(v, []).append(host.host_port)

    # Version consistency check
    if len(versions) == 1:
        version_str = next(iter(versions))
        section.cluster_checks.append(
            Check(
                name="Version consistency",
                status=STATUS_GREEN,
                value=version_str,
                message=f"All {len(hosts)} nodes running {version_str}",
            )
        )
    else:
        detail = "; ".join(
            f"{v}: {', '.join(h)}" for v, h in sorted(versions.items())
        )
        section.cluster_checks.append(
            Check(
                name="Version consistency",
                status=STATUS_RED,
                message=f"Inconsistent versions across cluster — {detail}",
            )
        )

    # Known-bad version check
    for version_str, host_list in versions.items():
        if version_str == "unknown":
            continue

        try:
            v = Version(version_str)
        except InvalidVersion:
            continue

        major_minor = f"{v.major}.{v.minor}"
        min_safe = MINIMUM_SAFE_VERSIONS.get(major_minor)
        if min_safe is None:
            continue

        try:
            min_safe_v = Version(min_safe)
        except InvalidVersion:
            continue

        if v < min_safe_v:
            section.cluster_checks.append(
                Check(
                    name="Known-bad version",
                    status=STATUS_RED,
                    value=version_str,
                    message=(
                        f"{version_str} is below minimum safe version "
                        f"{min_safe} — {VERSION_ISSUES}. "
                        f"Affected hosts: {', '.join(host_list)}"
                    ),
                )
            )
        else:
            section.cluster_checks.append(
                Check(
                    name="Known-bad version",
                    status=STATUS_GREEN,
                    value=version_str,
                    message=f"{version_str} meets minimum safe version ({min_safe})",
                )
            )

    return section
