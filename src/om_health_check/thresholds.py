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
    # If set, the deviation check is gated on the current value being at least
    # this large (or as small, for DIR_BELOW). Below this floor, deviation
    # comparisons are ignored regardless of mode — they're considered noise.
    # Lets a metric express "OP_EXECUTION_TIME_READS jumping 5x from 0.2ms to
    # 1ms is noise, but 5x from 30ms to 150ms is a real signal."
    relevance_floor: float | None = None


# ---------------------------------------------------------------------------
# Section 1: Connectivity & Infrastructure
# ---------------------------------------------------------------------------

# Network throughput is a weak standalone signal — a 3x jump from a few hundred
# KB/s is routine workload churn, not an incident. relevance_floor gates the
# deviation so only a surge past a meaningful absolute rate can fire. Tuned
# against a production report where sub-MB/s traffic at 3.3-3.4x baseline was noise.
SYSTEM_NETWORK_IN = Threshold(deviation=3.0, relevance_floor=5_000_000, mode=MODE_BASELINE)
SYSTEM_NETWORK_OUT = Threshold(deviation=3.0, relevance_floor=5_000_000, mode=MODE_BASELINE)
NETWORK_BYTES_IN = Threshold(deviation=3.0, relevance_floor=5_000_000, mode=MODE_BASELINE)
NETWORK_BYTES_OUT = Threshold(deviation=3.0, relevance_floor=5_000_000, mode=MODE_BASELINE)
NETWORK_NUM_REQUESTS = Threshold(deviation=3.0, relevance_floor=1000, mode=MODE_BASELINE)

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
    red=10.0, warn=5.0, direction=DIR_ABOVE,
    deviation=3.0, relevance_floor=2.0, mode=MODE_OR,
)
DISK_PARTITION_LATENCY_WRITE = Threshold(
    red=10.0, warn=5.0, direction=DIR_ABOVE,
    deviation=3.0, relevance_floor=2.0, mode=MODE_OR,
)
DISK_PARTITION_IOPS_READ = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_IOPS_WRITE = Threshold(red=950, direction=DIR_ABOVE, mode=MODE_ABSOLUTE)
DISK_PARTITION_SPACE_PERCENT_FREE = Threshold(
    red=10.0, warn=20.0, direction=DIR_BELOW, mode=MODE_ABSOLUTE,
)

# ---------------------------------------------------------------------------
# Section 4: Cache Resources
# ---------------------------------------------------------------------------

CACHE_USED_BYTES = Threshold(deviation=2.0, mode=MODE_BASELINE)
CACHE_DIRTY_BYTES = Threshold(deviation=3.0, mode=MODE_BASELINE)
CACHE_BYTES_READ_INTO = Threshold(
    red=1_000_000, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
CACHE_BYTES_WRITTEN_FROM = Threshold(
    red=1_000_000, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)

# ---------------------------------------------------------------------------
# Section 5: Database Activity & Workload
# ---------------------------------------------------------------------------

QUERY_TARGETING_SCANNED_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=2.0, mode=MODE_AND,
)
# Rate metrics use mode=AND: RED only when value is high enough to matter
# in absolute terms AND deviates from baseline. Pure baseline mode produces
# false positives on quiet clusters where 3x of "tiny" is still tiny.

QUERY_EXECUTOR_SCANNED = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
QUERY_EXECUTOR_SCANNED_OBJECTS = Threshold(
    red=1000, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)

DOCUMENT_METRICS_RETURNED = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
# Document write rates: red=10/s was too sensitive for production — 11 inserts/s
# at 3.6x baseline fired RED on a real prod cluster, which is trivial write
# volume. Raised to 100/s so a write-rate RED means a genuine surge (100+/s AND
# 3x baseline).
DOCUMENT_METRICS_INSERTED = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
DOCUMENT_METRICS_UPDATED = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
DOCUMENT_METRICS_DELETED = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)

OPERATIONS_SCAN_AND_ORDER = Threshold(
    red=1.0, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)

OPCOUNTER_CMD = Threshold(
    red=20, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
OPCOUNTER_QUERY = Threshold(
    red=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
OPCOUNTER_UPDATE = Threshold(
    red=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
OPCOUNTER_DELETE = Threshold(
    red=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
OPCOUNTER_GETMORE = Threshold(
    red=10, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)
# Raised 10 -> 100 to match DOCUMENT_METRICS_INSERTED (same underlying inserts);
# 11/s fired RED on prod. The rest of the OPCOUNTER_* family is still at red=10
# pending the getMore-driven review of the whole family.
OPCOUNTER_INSERT = Threshold(
    red=100, direction=DIR_ABOVE, deviation=3.0, mode=MODE_AND,
)

OP_EXECUTION_TIME_READS = Threshold(
    red=100, warn=50, direction=DIR_ABOVE,
    deviation=2.0, relevance_floor=20, mode=MODE_OR,
)
OP_EXECUTION_TIME_WRITES = Threshold(
    red=100, warn=50, direction=DIR_ABOVE,
    deviation=2.0, relevance_floor=20, mode=MODE_OR,
)
OP_EXECUTION_TIME_COMMANDS = Threshold(
    red=100, warn=50, direction=DIR_ABOVE,
    deviation=2.0, relevance_floor=20, mode=MODE_OR,
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

# Replication lag (per-secondary, seconds). Outside of post-restart catch-up
# windows, lag should be near zero. RED if a secondary is more than 10s
# behind; WARN at 2s.
OPLOG_REPLICATION_LAG_TIME = Threshold(
    red=10, warn=2, direction=DIR_ABOVE, mode=MODE_ABSOLUTE,
)
# Oplog window (hours of write history retained). RED if under 24h of
# buffer, WARN under 36h.
OPLOG_MASTER_TIME = Threshold(
    red=24, warn=36, direction=DIR_BELOW, mode=MODE_ABSOLUTE,
)
# Oplog write rate is informational only — "high" depends entirely on
# the workload, and a baseline comparison just adds noise. No thresholds
# means it shows up in the report without claiming a status.
OPLOG_RATE_GB_PER_HOUR = Threshold(mode=MODE_ABSOLUTE)

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
    "SYSTEM_NETWORK_IN": SYSTEM_NETWORK_IN,
    "SYSTEM_NETWORK_OUT": SYSTEM_NETWORK_OUT,
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
    # Section 4
    "CACHE_USED_BYTES": CACHE_USED_BYTES,
    "CACHE_DIRTY_BYTES": CACHE_DIRTY_BYTES,
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
