"""Centralized threshold and baseline deviation configuration for all metrics.

Check modules import from here — no hardcoded thresholds in check code.

Thresholds can be overridden via a YAML config file. The file only needs to
specify metrics the user wants to change; everything else uses defaults.

Example config file (~/.om-health-check.yaml):

    thresholds:
      CONNECTIONS:
        red: 30000
        warn: 25000
      SYSTEM_NORMALIZED_CPU_USER:
        red: 90.0
        mode: "or"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

# Evaluation modes
MODE_ABSOLUTE = "absolute"  # RED if value crosses threshold; baseline is informational
MODE_BASELINE = "baseline"  # RED only on deviation from baseline; no absolute threshold
MODE_AND = "and"            # RED only if threshold crossed AND baseline deviated
MODE_OR = "or"              # RED if threshold crossed OR baseline deviated

# Direction
DIR_ABOVE = "above"  # RED when value >= red
DIR_BELOW = "below"  # RED when value <= red


@dataclass(frozen=True)
class Threshold:
    red: float | None = None
    warn: float | None = None
    direction: str = DIR_ABOVE
    deviation: float | None = None
    mode: str = MODE_ABSOLUTE


# ---------------------------------------------------------------------------
# Section 1: Connectivity & Infrastructure
# ---------------------------------------------------------------------------

RESTARTS_IN_LAST_HOUR = Threshold(red=0, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)

SYSTEM_NETWORK_BYTES_IN = Threshold(deviation=3.0, mode=MODE_BASELINE)
SYSTEM_NETWORK_BYTES_OUT = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_BYTES_IN = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_BYTES_OUT = Threshold(deviation=3.0, mode=MODE_BASELINE)
NETWORK_NUM_REQUESTS = Threshold(deviation=3.0, mode=MODE_BASELINE)

# ---------------------------------------------------------------------------
# Section 2: Compute Resources
# ---------------------------------------------------------------------------

SYSTEM_NORMALIZED_CPU_USER = Threshold(
    red=95.0, warn=80.0, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
SYSTEM_NORMALIZED_CPU_IOWAIT = Threshold(
    red=20.0, warn=10.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
PROCESS_NORMALIZED_CPU_USER = Threshold(
    red=80.0, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
SYSTEM_MEMORY_AVAILABLE = Threshold(
    red=500, warn=1000, direction=DIR_BELOW, deviation=0.3, mode=MODE_OR,
)
MEMORY_RESIDENT = Threshold(deviation=2.0, mode=MODE_BASELINE)
SWAP_USAGE_USED = Threshold(red=100, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)

# ---------------------------------------------------------------------------
# Section 3: Disk Resources
# ---------------------------------------------------------------------------

DISK_PARTITION_LATENCY_READ = Threshold(
    red=10.0, warn=5.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)
DISK_PARTITION_LATENCY_WRITE = Threshold(
    red=10.0, warn=5.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)
DISK_PARTITION_IOPS_READ = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_IOPS_WRITE = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_SPACE_PERCENT_FREE = Threshold(
    red=10.0, warn=20.0, direction=DIR_BELOW, mode=MODE_ABSOLUTE,
)
DISK_PARTITION_QUEUE_DEPTH = Threshold(
    red=10, warn=5, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)

# ---------------------------------------------------------------------------
# Section 4: Cache Resources
# ---------------------------------------------------------------------------

CACHE_FILL_RATIO = Threshold(red=95.0, warn=80.0, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DIRTY_FILL_RATIO = Threshold(red=5.0, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
CACHE_BYTES_READ_INTO = Threshold(deviation=3.0, mode=MODE_BASELINE)
CACHE_BYTES_WRITTEN_FROM = Threshold(deviation=3.0, mode=MODE_BASELINE)

# ---------------------------------------------------------------------------
# Section 5: Database Activity & Workload
# ---------------------------------------------------------------------------

QUERY_TARGETING_SCANNED_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
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
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR,
)
OP_EXECUTION_TIME_WRITES = Threshold(
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR,
)
OP_EXECUTION_TIME_COMMANDS = Threshold(
    red=100, warn=50, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR,
)

GLOBAL_LOCK_CURRENT_QUEUE_READERS = Threshold(
    red=10, warn=5, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)
GLOBAL_LOCK_CURRENT_QUEUE_WRITERS = Threshold(
    red=10, warn=5, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)
GLOBAL_LOCK_CURRENT_QUEUE_TOTAL = Threshold(
    red=20, warn=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_OR,
)

# ---------------------------------------------------------------------------
# Section 6: Replication
# ---------------------------------------------------------------------------

OPLOG_REPLICATION_LAG_TIME = Threshold(
    red=60, warn=10, direction=DIR_ABOVE, mode=MODE_ABSOLUTE,
)
OPLOG_MASTER_TIME = Threshold(
    red=24, warn=48, direction=DIR_BELOW, mode=MODE_ABSOLUTE,
)
OPLOG_RATE_GB_PER_HOUR = Threshold(deviation=3.0, mode=MODE_BASELINE)

# ---------------------------------------------------------------------------
# Section 7: Connections
# ---------------------------------------------------------------------------

CONNECTIONS = Threshold(
    red=25000, warn=20000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_OR,
)

# ---------------------------------------------------------------------------
# Lookup by metric name
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, Threshold] = {
    # Section 1
    "RESTARTS_IN_LAST_HOUR": RESTARTS_IN_LAST_HOUR,
    "SYSTEM_NETWORK_BYTES_IN": SYSTEM_NETWORK_BYTES_IN,
    "SYSTEM_NETWORK_BYTES_OUT": SYSTEM_NETWORK_BYTES_OUT,
    "NETWORK_BYTES_IN": NETWORK_BYTES_IN,
    "NETWORK_BYTES_OUT": NETWORK_BYTES_OUT,
    "NETWORK_NUM_REQUESTS": NETWORK_NUM_REQUESTS,
    # Section 2
    "SYSTEM_NORMALIZED_CPU_USER": SYSTEM_NORMALIZED_CPU_USER,
    "SYSTEM_NORMALIZED_CPU_IOWAIT": SYSTEM_NORMALIZED_CPU_IOWAIT,
    "PROCESS_NORMALIZED_CPU_USER": PROCESS_NORMALIZED_CPU_USER,
    "SYSTEM_MEMORY_AVAILABLE": SYSTEM_MEMORY_AVAILABLE,
    "MEMORY_RESIDENT": MEMORY_RESIDENT,
    "SWAP_USAGE_USED": SWAP_USAGE_USED,
    # Section 3
    "DISK_PARTITION_LATENCY_READ": DISK_PARTITION_LATENCY_READ,
    "DISK_PARTITION_LATENCY_WRITE": DISK_PARTITION_LATENCY_WRITE,
    "DISK_PARTITION_IOPS_READ": DISK_PARTITION_IOPS_READ,
    "DISK_PARTITION_IOPS_WRITE": DISK_PARTITION_IOPS_WRITE,
    "DISK_PARTITION_SPACE_PERCENT_FREE": DISK_PARTITION_SPACE_PERCENT_FREE,
    "DISK_PARTITION_QUEUE_DEPTH": DISK_PARTITION_QUEUE_DEPTH,
    # Section 4
    "CACHE_FILL_RATIO": CACHE_FILL_RATIO,
    "DIRTY_FILL_RATIO": DIRTY_FILL_RATIO,
    "CACHE_BYTES_READ_INTO": CACHE_BYTES_READ_INTO,
    "CACHE_BYTES_WRITTEN_FROM": CACHE_BYTES_WRITTEN_FROM,
    # Section 5
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
    # Section 6
    "OPLOG_REPLICATION_LAG_TIME": OPLOG_REPLICATION_LAG_TIME,
    "OPLOG_MASTER_TIME": OPLOG_MASTER_TIME,
    "OPLOG_RATE_GB_PER_HOUR": OPLOG_RATE_GB_PER_HOUR,
    # Section 7
    "CONNECTIONS": CONNECTIONS,
}


def get_threshold(metric_name: str) -> Threshold | None:
    """Look up threshold config for a metric name. Returns None if not configured."""
    return THRESHOLDS.get(metric_name)


def load_overrides(config_path: str | Path | None = None) -> None:
    """Load threshold overrides from a YAML config file.

    Searches in order:
      1. Explicit path passed as argument
      2. Path in OM_HEALTH_CHECK_CONFIG environment variable
      3. ~/.om-health-check.yaml

    If no file is found, defaults are used silently.
    Only the ``thresholds`` key is read; unknown metric names are ignored.
    Each metric entry may specify any subset of Threshold fields —
    unspecified fields retain their default values.
    """
    try:
        import yaml
    except ImportError:
        # PyYAML not installed — skip config file loading
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
        if metric_name not in THRESHOLDS:
            continue
        if not isinstance(values, dict):
            continue

        # Start from the existing default and override specified fields
        default = THRESHOLDS[metric_name]
        kwargs = {f.name: getattr(default, f.name) for f in fields(Threshold)}
        for key, val in values.items():
            if key in valid_fields:
                kwargs[key] = val
        THRESHOLDS[metric_name] = Threshold(**kwargs)
