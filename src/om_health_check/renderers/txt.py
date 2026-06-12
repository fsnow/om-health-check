"""Plain text renderer — output suitable for pasting into MIM tickets."""

from __future__ import annotations

from om_health_check.models import Check, ClusterReport, Report, Section


def render(report: Report) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("OM HEALTH CHECK REPORT")
    lines.append(f"Started:     {report.started_at}")
    if report.finished_at:
        lines.append(f"Finished:    {report.finished_at}")
        elapsed = report.elapsed_seconds
        if elapsed is not None:
            lines.append(f"Elapsed:     {elapsed:.1f}s")
    lines.append(f"Ops Manager: {report.om_url}")
    lines.append(f"Overall:     [{report.overall_status}]")
    lines.append("=" * 72)

    for cr in report.clusters:
        lines.append("")
        lines.append("-" * 72)
        lines.append(
            f"Cluster: {cr.cluster_name}  |  Project: {cr.project_name}  |  "
            f"[{cr.overall_status}]"
        )
        lines.append("-" * 72)

        for section in cr.sections:
            lines.append("")
            lines.append(f"  ## {section.name}  [{section.status}]")

            # Cluster-level checks
            for check in section.cluster_checks:
                lines.append(_format_check(check, indent=4))

            # Per-host checks
            for hs in section.hosts:
                lines.append(f"    -- {hs.host} ({hs.role})")
                for check in hs.checks:
                    lines.append(_format_check(check, indent=6))

        # Summary
        lines.append("")
        red, green, info, warn = _count_statuses(cr)
        lines.append(
            f"  Summary: {red} RED, {warn} WARN, {info} INFO, {green} GREEN"
        )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def _format_check(check: Check, indent: int) -> str:
    pad = " " * indent
    status_tag = f"[{check.status}]"
    parts = [f"{pad}{status_tag:7s} {check.name}"]
    if check.message:
        parts.append(f" — {check.message}")
    return "".join(parts)


def _count_statuses(cr: ClusterReport) -> tuple[int, int, int, int]:
    red = green = info = warn = 0
    for section in cr.sections:
        for check in section.cluster_checks:
            if check.status == "RED":
                red += 1
            elif check.status == "GREEN":
                green += 1
            elif check.status == "WARN":
                warn += 1
            else:
                info += 1
        for hs in section.hosts:
            for check in hs.checks:
                if check.status == "RED":
                    red += 1
                elif check.status == "GREEN":
                    green += 1
                elif check.status == "WARN":
                    warn += 1
                else:
                    info += 1
    return red, green, info, warn
