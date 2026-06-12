"""Configuration dataclass built from CLI args and environment variables."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    om_url: str
    username: str
    api_key: str
    project_names: list[str]
    cluster_name: str | None = None
    formats: list[str] | None = None
    baseline_lookback: str | None = None  # e.g. "7d", "4h", "30m"; None = default 7d
    rate_limit: float = 2.0  # OM API requests/second (default conservative)
    max_workers: int = 10  # threads for per-host parallelism
    min_status: str = "GREEN"  # GREEN (all) | INFO | WARN | RED — txt-only filter

    def __post_init__(self):
        if self.formats is None:
            object.__setattr__(self, "formats", ["txt"])
