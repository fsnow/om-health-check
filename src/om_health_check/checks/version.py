"""Section 9: Version Information checks."""

from __future__ import annotations

import os
from pathlib import Path

from packaging.version import Version, InvalidVersion

from opsmanager.types import Cluster, Host

from om_health_check.client import HealthCheckClient
from om_health_check.models import (
    STATUS_GREEN,
    STATUS_INFO,
    STATUS_RED,
    STATUS_WARN,
    Check,
    Section,
)

# Minimum safe versions — below these have known CVEs or critical bugs.
# Key is "major.minor", value is minimum safe patch version.
#
# Per customer default, a version below its minimum is reported at INFO
# severity (see VERSION_SEVERITY), not RED: version currency is tracked and
# highlighted, but is not treated as an active incident on its own. Both the
# minimums and the severity can be overridden via the `version:` block of the
# YAML config file.
#
# 9.0 is listed pre-emptively so that when a cluster upgrades to the 9.0 line
# it is recognized rather than falling through to "no known-bad version data".
# The 9.0.0 floor is a placeholder to bump when real 9.0 advisories land.
MINIMUM_SAFE_VERSIONS = {
    "7.0": "7.0.37",
    "8.0": "8.0.26",
    "8.2": "8.2.11",
    "8.3": "8.3.4",
    "9.0": "9.0.0",
}

# Severity applied to version-currency findings (below-minimum, mixed
# versions). Customer default is INFO; override via `version.severity`.
_SEVERITY_BY_NAME = {
    "info": STATUS_INFO,
    "warn": STATUS_WARN,
    "warning": STATUS_WARN,
    "red": STATUS_RED,
    "critical": STATUS_RED,
}
VERSION_SEVERITY = STATUS_INFO

# Optional advisory note per major.minor line, appended to a below-minimum
# finding (e.g. the CVEs that the minimum patch addresses). Deliberately empty
# in code — advisory text goes stale, so it lives only in the YAML config
# (`version.version_notes`) where it can be maintained without touching this
# script.
VERSION_NOTES: dict[str, str] = {}


def load_version_overrides(config_path: str | Path | None = None) -> None:
    """Load `version:` config overrides (minimum_safe_versions, notes, severity).

    Uses the same file-search order as thresholds.load_overrides. Silently
    does nothing if PyYAML is missing, no config file is found, or the file
    has no `version:` block.
    """
    try:
        import yaml
    except ImportError:
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
    version_cfg = data.get("version")
    if not isinstance(version_cfg, dict):
        return

    global VERSION_SEVERITY
    severity = version_cfg.get("severity")
    if isinstance(severity, str) and severity.lower() in _SEVERITY_BY_NAME:
        VERSION_SEVERITY = _SEVERITY_BY_NAME[severity.lower()]

    mins = version_cfg.get("minimum_safe_versions")
    if isinstance(mins, dict):
        # Merge: listed lines override defaults, unlisted lines keep defaults.
        MINIMUM_SAFE_VERSIONS.update({str(k): str(v) for k, v in mins.items()})

    notes = version_cfg.get("version_notes")
    if isinstance(notes, dict):
        VERSION_NOTES.update({str(k): str(v) for k, v in notes.items()})


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

    if not versions:
        section.cluster_checks.append(
            Check(
                name="Version consistency",
                status=STATUS_INFO,
                message="No version data available",
            )
        )
        return section

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
                status=VERSION_SEVERITY,
                message=f"Inconsistent versions across cluster — {detail}",
            )
        )

    # Version check — flag known-bad MongoDB versions
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
            note = VERSION_NOTES.get(major_minor)
            message = f"{version_str} is below minimum safe version {min_safe}"
            if note:
                message += f" — {note}"
            message += f". Affected hosts: {', '.join(host_list)}"
            section.cluster_checks.append(
                Check(
                    name="Version check",
                    status=VERSION_SEVERITY,
                    value=version_str,
                    message=message,
                )
            )
        else:
            section.cluster_checks.append(
                Check(
                    name="Version check",
                    status=STATUS_GREEN,
                    value=version_str,
                    message=f"{version_str} meets minimum safe version ({min_safe})",
                )
            )

    return section
