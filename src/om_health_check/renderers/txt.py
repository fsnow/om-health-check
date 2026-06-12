"""Plain text renderer — output suitable for pasting into MIM tickets."""

from __future__ import annotations

from om_health_check.models import Check, ClusterReport, Report, Section

_STATUS_RANK = {"GREEN": 0, "INFO": 1, "WARN": 2, "RED": 3}


def render(report: Report, min_status: str = "GREEN") -> str:
    """Render the report. min_status filters check lines:
       GREEN (default) shows everything; WARN shows only WARN/RED; RED shows only RED.
       Cluster header, summary, and topology line are always shown.
    """
    min_rank = _STATUS_RANK.get(min_status.upper(), 0)
    brief = min_rank > 0

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
    if brief:
        lines.append(f"Filter:      showing checks with status >= {min_status.upper()}")
    lines.append("=" * 72)

    for cr in report.clusters:
        lines.append("")
        lines.append("-" * 72)
        lines.append(
            f"Cluster: {cr.cluster_name}  |  Project: {cr.project_name}  |  "
            f"[{cr.overall_status}]"
        )
        lines.append("-" * 72)
        if cr.topology:
            lines.append(f"  Topology: {cr.topology.summary_line()}")
        red, green, info, warn = _count_statuses(cr)
        lines.append(
            f"  Summary:  {red} RED, {warn} WARN, {info} INFO, {green} GREEN"
        )

        for section in cr.sections:
            section_lines = _render_section(section, min_rank)
            if section_lines:
                lines.append("")
                lines.extend(section_lines)

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def _render_section(section: Section, min_rank: int) -> list[str]:
    """Render one section. Returns [] if everything is filtered out."""
    body: list[str] = []

    # Cluster-level checks
    for check in section.cluster_checks:
        if _STATUS_RANK.get(check.status, 0) >= min_rank:
            body.append(_format_check(check, indent=4))

    # Per-host checks
    for hs in section.hosts:
        host_lines = []
        for check in hs.checks:
            if _STATUS_RANK.get(check.status, 0) >= min_rank:
                host_lines.append(_format_check(check, indent=6))
        if host_lines:
            body.append(f"    -- {hs.host} ({hs.role})")
            body.extend(host_lines)

    if not body and min_rank > 0:
        return []
    return [f"  ## {section.name}  [{section.status}]"] + body


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
