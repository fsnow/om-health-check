"""JSON renderer — machine-readable output."""

from __future__ import annotations

import json

from om_health_check.models import Report


def render(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2)
