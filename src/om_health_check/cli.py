"""CLI entry point for om-health-check."""

from __future__ import annotations

import argparse
import os
import sys

from om_health_check.config import Config
from om_health_check.runner import run
from om_health_check.thresholds import load_overrides


VALID_FORMATS = {"txt", "json", "html"}


def _parse_formats(value: str) -> list[str]:
    formats = [f.strip().lower() for f in value.split(",")]
    invalid = set(formats) - VALID_FORMATS
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Invalid format(s): {', '.join(sorted(invalid))}. "
            f"Valid formats: {', '.join(sorted(VALID_FORMATS))}"
        )
    return formats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="om-health-check",
        description="MongoDB Ops Manager automated health check tool",
    )
    parser.add_argument(
        "--om-url",
        required=True,
        help="Ops Manager base URL",
    )
    parser.add_argument(
        "--project",
        action="append",
        required=True,
        dest="projects",
        help="Project name (repeatable)",
    )
    parser.add_argument(
        "--cluster",
        default=None,
        help="Cluster name filter (omit to check all clusters)",
    )
    parser.add_argument(
        "--format",
        default="txt",
        type=_parse_formats,
        dest="formats",
        help="Output format: txt, json, html, or comma-separated (default: txt)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file for threshold overrides "
        "(default: ~/.om-health-check.yaml)",
    )
    parser.add_argument(
        "--baseline-lookback",
        default=None,
        dest="baseline_lookback",
        help="Baseline lookback window (default: 7d). Format: <N>d|h|m, "
        "e.g. '7d', '4h', '30m'. Useful for testing against newly-built OM "
        "instances that don't yet have 1 week of history.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        dest="rate_limit",
        help="Maximum API requests per second sent to Ops Manager (default: 2). "
        "The default is conservative to protect production OM instances. Bump "
        "to 5-10 for faster runs when OM has headroom; large sharded clusters "
        "may require this for the report to complete in a reasonable time.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        dest="max_workers",
        help="Maximum threads used for per-host API calls within each check "
        "section (default: 10). Note: total throughput is also bounded by "
        "--rate-limit; parallelism only helps once rate-limit is bumped above "
        "the network round-trip rate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    username = os.environ.get("OPS_MANAGER_USER")
    api_key = os.environ.get("OPS_MANAGER_API_KEY")

    if not username or not api_key:
        print(
            "Error: OPS_MANAGER_USER and OPS_MANAGER_API_KEY environment "
            "variables must be set.",
            file=sys.stderr,
        )
        return 1

    load_overrides(args.config)

    config = Config(
        om_url=args.om_url,
        username=username,
        api_key=api_key,
        project_names=args.projects,
        cluster_name=args.cluster,
        formats=args.formats,
        baseline_lookback=args.baseline_lookback,
        rate_limit=args.rate_limit,
        max_workers=args.max_workers,
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
