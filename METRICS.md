# Metrics Reference

This document explains every check the tool performs: what each metric measures,
the units it is reported in, and the exact criteria used to assign a status.

It is generated to match the shipped default thresholds. Any threshold can be
overridden per environment in a YAML config — see
[Overriding thresholds](#overriding-thresholds) and
[`examples/all-thresholds.yaml`](examples/all-thresholds.yaml).

- [How evaluation works](#how-evaluation-works)
- [Sections](#sections)
  1. [Connectivity & Infrastructure](#1-connectivity--infrastructure)
  2. [Compute Resources](#2-compute-resources)
  3. [Disk Resources](#3-disk-resources)
  4. [Cache Resources](#4-cache-resources)
  5. [Database Activity & Workload](#5-database-activity--workload)
  6. [Oplog](#6-oplog)
  7. [Replication](#7-replication)
  8. [Connections](#8-connections)
  9. [Backup](#9-backup)
  10. [Version Information](#10-version-information)
- [Overriding thresholds](#overriding-thresholds)

---

## How evaluation works

### Statuses

| Status | Meaning |
|---|---|
| **GREEN** | Healthy. |
| **WARN** | Approaching a threshold, or a condition worth noting during triage. |
| **RED** | A threshold was crossed or a significant baseline deviation occurred — an actionable problem. |
| **INFO** | Informational only: missing data, advisory alerts, expected-by-design values, or a check that could not be fully evaluated. **INFO never colors the overall status.** |

**Roll-up:** a section's status is the worst of its non-INFO checks; the
cluster's status is the worst of its sections; the overall status is the worst
of its clusters.

### Current value vs. baseline

- **Current value** — the 1-hour rolling average of per-minute (PT1M) samples,
  so a single transient spike does not swing a result.
- **Baseline** — the value from **one week prior**, same hour and same day of
  week, aggregated over 1 hour. This compares like-for-like: Monday 09:00 this
  week against Monday 09:00 last week, so normal daily/weekly workload shape is
  not mistaken for an anomaly. If no baseline exists (cluster too new, or
  monitoring gap), baseline-dependent checks report INFO rather than guessing.

### Evaluation modes

Every metric's criteria are one of four modes. They appear in the report
messages.

| Mode | RED when… |
|---|---|
| **absolute** | The value crosses a fixed threshold. Baseline is not used. |
| **baseline** | The value deviates from baseline by ≥ the configured multiple, **and** the value is past the `relevance_floor` (see below). No fixed "bad" value. |
| **or** | *Either* a fixed threshold is crossed *or* an above-floor deviation occurs. Used for genuine concerns (CPU %, targeting ratios) where a steadily-high value should fire on its own. |
| **and** | *Both* a fixed threshold and a baseline deviation are met. A valid mode a config may set, but not used by any default threshold. |

### The relevance floor

A rate metric (operations/sec, bytes/sec) has no inherently "bad" value — a high
rate just means a busy cluster. What matters is an unusual **spike**, but only
once the rate is high enough to be worth attention. The `relevance_floor` is the
absolute value the current reading must reach before a deviation is considered:

> A 3× jump from 2/sec to 6/sec is noise and is ignored; a 3× jump from
> 5,000/sec to 15,000/sec is flagged.

The floor is checked against the **current** value, never the baseline.

### Unit conversions

Ops Manager returns a few metrics in units that differ from how they are most
useful to read. The tool converts these at the source, so the value, threshold,
and displayed unit all agree:

| Metric | Ops Manager unit | Reported as |
|---|---|---|
| `SWAP_USAGE_USED`, `SYSTEM_MEMORY_AVAILABLE` | kilobytes | megabytes |
| `OPLOG_MASTER_TIME` | seconds | hours |

---

## Sections

The tool checks 10 sections per cluster, in the order below. Rate and
percentage metrics are evaluated **per host**; a handful of checks
(agent status, alerts, backup, version) are evaluated **per cluster**. `mongos`
routers are skipped for metrics that do not apply to them (no oplog, no
WiredTiger cache, no per-document metrics).

---

### 1. Connectivity & Infrastructure

Reachability, node state, open alerts, monitoring-agent health, and network
throughput.

**Cluster / node checks (not threshold-based):**

| Check | Logic |
|---|---|
| OM API reachability | GREEN when the Ops Manager API responds; RED on failure. |
| Node status | GREEN when the node is enabled and not DOWN. A node reporting a DOWN replica state is **RED** (unreachable data node). A node disabled in Ops Manager is **INFO** (an intentional admin action, not a fault). |
| Active alerts | An open non-advisory Ops Manager alert for the cluster is **RED** (Ops Manager's own severity is passed through). Advisory alert types are **INFO**. No open alerts is GREEN. |
| Agent status | Monitoring is project-wide: exactly one agent is ACTIVE, the rest STANDBY. Missing agents, or no ACTIVE agent, is **WARN** — a monitoring-visibility gap, not a MongoDB fault. |

**Network throughput (per host):**

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `SYSTEM_NETWORK_IN` / `_OUT` | Host-wide network throughput (includes non-mongod traffic). | bytes/sec | baseline; RED at ≥3× baseline once ≥5 MB/s |
| `NETWORK_BYTES_IN` / `_OUT` | mongod process network throughput. | bytes/sec | baseline; RED at ≥3× baseline once ≥5 MB/s |
| `NETWORK_NUM_REQUESTS` | mongod requests handled. | requests/sec | baseline; RED at ≥3× baseline once ≥1,000/sec |

Network throughput is a weak standalone signal, so the floors are high — a
spike only registers on genuinely heavy traffic. It is most useful correlated
with other findings (e.g. a connection storm plus a network surge).

---

### 2. Compute Resources

CPU, memory, and swap. CPU percentages are **normalized** (per-vCPU: 100% means
one core fully used, independent of core count).

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `SYSTEM_NORMALIZED_CPU_USER` | Host CPU spent in user space. | % | or; RED ≥95% or ≥2× baseline (above 80%); WARN 80–95% |
| `SYSTEM_NORMALIZED_CPU_IOWAIT` | Host CPU waiting on I/O — a disk-bound signal. | % | or; RED ≥20% or ≥3× baseline (above 10%); WARN 10–20% |
| `PROCESS_NORMALIZED_CPU_USER` | CPU used by the mongod process itself. | % | or; RED ≥80% or ≥2× baseline (above 50%) |
| `SYSTEM_MEMORY_AVAILABLE` | Memory available to the host. | MB | or; RED below 500 MB or dropped to ≤0.3× baseline; WARN below 1,000 MB |
| `MEMORY_RESIDENT` | mongod resident set size (physical RAM in use). | MB | baseline; RED at ≥2× baseline |
| `SWAP_USAGE_USED` | Swap in use. MongoDB should not swap. | MB | absolute; RED above 100 MB |

For CPU, `mode=or` means a box that is *steadily* pegged (e.g. 97% every hour,
so not "deviating") still fires on the absolute threshold — the deviation half
is a floor-gated early warning, not a requirement.

**Deeper CPU/memory drill-down (INFO):** when any of the metrics above is RED,
the tool additionally pulls `SYSTEM_NORMALIZED_CPU_{STEAL,GUEST,SOFTIRQ,IRQ,NICE,KERNEL}`
and `SWAP_USAGE_FREE` and reports them as **INFO** context, to help pinpoint
where the CPU time is going. They are never graded.

---

### 3. Disk Resources

Per data partition.

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `DISK_PARTITION_LATENCY_READ` / `_WRITE` | Average I/O latency for the partition. | ms | or; RED ≥10 ms or ≥3× baseline (above 2 ms); WARN ≥5 ms |
| `DISK_PARTITION_IOPS_READ` / `_WRITE` | I/O operations per second. | IOPS | absolute; RED above 950 (near a common provisioned-IOPS ceiling) |
| `DISK_PARTITION_SPACE_PERCENT_FREE` | Free space on the partition. | % | absolute; RED below 10% free; WARN below 20% |

The latency floor (2 ms) keeps a healthy-but-jumpy sub-millisecond disk from
firing on a large multiple of a tiny baseline.

---

### 4. Cache Resources

WiredTiger storage-engine cache (mongod only; skipped on `mongos`).

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `CACHE_USED_BYTES` | Bytes currently held in the WiredTiger cache. | bytes | baseline; RED at ≥2× baseline |
| `CACHE_DIRTY_BYTES` | Modified ("dirty") bytes not yet written to disk. | bytes | baseline; RED at ≥3× baseline |
| `CACHE_BYTES_READ_INTO` | Rate data is read from disk into cache (cache-miss pressure). | bytes/sec | baseline; RED at ≥3× baseline once ≥1 MB/s |
| `CACHE_BYTES_WRITTEN_FROM` | Rate dirty data is flushed from cache to disk. | bytes/sec | baseline; RED at ≥3× baseline once ≥1 MB/s |

---

### 5. Database Activity & Workload

Query efficiency, throughput, latency, lock queues, and index advice
(mongod only; skipped on `mongos`).

**Query targeting** — efficiency ratios, where a high value means work wasted
scanning documents that are not returned:

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `QUERY_TARGETING_SCANNED_PER_RETURNED` | Index keys scanned per document returned. | ratio | or; RED ≥1,000 or ≥2× baseline (above 100) |
| `QUERY_TARGETING_SCANNED_OBJECTS_PER_RETURNED` | Documents scanned per document returned. | ratio | or; RED ≥1,000 or ≥2× baseline (above 100) |

**Throughput / scan rates** — pure rates, evaluated as baseline deviations
above a floor:

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `QUERY_EXECUTOR_SCANNED` | Index keys examined. | ops/sec | baseline; ≥3× baseline once ≥10,000/sec |
| `QUERY_EXECUTOR_SCANNED_OBJECTS` | Documents examined. | ops/sec | baseline; ≥3× baseline once ≥10,000/sec |
| `DOCUMENT_METRICS_RETURNED` | Documents returned to clients. | ops/sec | baseline; ≥3× baseline once ≥10,000/sec |
| `DOCUMENT_METRICS_INSERTED` / `_UPDATED` / `_DELETED` | Document write rates. | ops/sec | baseline; ≥3× baseline once ≥1,000/sec |
| `OPERATIONS_SCAN_AND_ORDER` | Queries that sorted in memory (no supporting index). | ops/sec | baseline; ≥3× baseline once ≥100/sec |
| `OPCOUNTER_QUERY` / `_INSERT` / `_UPDATE` / `_DELETE` / `_GETMORE` / `_CMD` | Operation counters by type. | ops/sec | baseline; ≥3× baseline once ≥1,000/sec |

> **`OPCOUNTER_GETMORE` on secondaries** is reported as **INFO**, not graded —
> secondaries continuously issue getMores to tail the primary's oplog, so an
> elevated value there is expected replication traffic, not a workload anomaly.
> It is graded normally on primaries.

**Operation latency:**

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `OP_EXECUTION_TIME_READS` / `_WRITES` / `_COMMANDS` | Average operation execution time. | ms | or; RED ≥100 ms or ≥2× baseline (above 20 ms); WARN ≥50 ms |

**Lock queues** — operations waiting on the global lock:

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `GLOBAL_LOCK_CURRENT_QUEUE_READERS` / `_WRITERS` | Readers / writers queued for the lock. | operations | or; RED ≥10 or ≥3× baseline; WARN ≥5 |
| `GLOBAL_LOCK_CURRENT_QUEUE_TOTAL` | Total queued operations. | operations | or; RED ≥20 or ≥3× baseline; WARN ≥10 |

**Performance Advisor** (per host): reports Ops Manager's suggested indexes.
Any suggestions → **RED** with the affected namespaces; none → GREEN. If
Performance Advisor is unavailable or access is denied, the check is **INFO**
(it commonly requires the Project Data Access Read Only role or higher). The
tool intentionally does not read slow-query logs, to avoid transferring query
content — suggested indexes carry the same actionable signal.

---

### 6. Oplog

Oplog capacity and write rate, per replica-set member. Separate from
replication lag (Section 7).

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `OPLOG_MASTER_TIME` | The oplog window — how far back in time the oplog reaches. Determines how long a secondary can be offline before needing a full resync, and the recovery cushion for backups. | hours | absolute; RED below 24 h; WARN below 36 h |
| `OPLOG_RATE_GB_PER_HOUR` | Rate the oplog is being written. | GB/hr | informational — reported, not graded (the meaningful level is workload-specific) |

---

### 7. Replication

Per secondary. Separate from oplog capacity (Section 6).

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `OPLOG_REPLICATION_LAG_TIME` | How far a secondary trails the primary. | seconds | absolute; RED above 10 s; WARN above 2 s |

Outside of a post-restart catch-up window, lag should be near zero on a healthy
cluster. Only secondaries are evaluated — a primary does not lag itself.

---

### 8. Connections

| Metric | What it measures | Units | Criteria |
|---|---|---|---|
| `CONNECTIONS` | Open connections to the mongod. | connections | or; RED ≥25,000 or ≥2× baseline; WARN ≥20,000 |

When a connection count is elevated **and** operation latency is also elevated,
the tool adds an **INFO** note that the connection spike may be a symptom of
slow operations rather than the root cause.

---

### 9. Backup

Cluster-level, evaluated from Ops Manager backup state.

| Check | Logic |
|---|---|
| Backup configuration | GREEN when backup is enabled and active (STARTED). Any other state, or backup not configured, is **INFO**. |
| Snapshot in progress | A snapshot actively being captured when the check runs is **WARN** — expected activity, not a fault, but surfaced because snapshot I/O can affect the cluster during triage. |
| Backup capture lag | GREEN when the latest snapshot is within its expected interval (plus a 50% grace window); **RED** when overdue, or when no snapshots exist at all. |

If snapshot schedule/history is unavailable (for example the `snapshotSchedule`
resource returns 404), no line is emitted — the "backup is enabled and active"
status already conveys the primary objective, that backup is running.

---

### 10. Version Information

Cluster-level. By default these findings are **INFO** — version currency is
tracked and highlighted but not treated as an incident on its own. The severity
and the minimum-safe versions are configurable (see below).

| Check | Logic |
|---|---|
| Version consistency | GREEN when all nodes run the same version; **INFO** (default severity) when versions are mixed, e.g. mid-upgrade. |
| Version check | For each version, compared against the minimum-safe patch level for its release line. Below the minimum → **INFO** (default severity), with the associated advisory note; at or above → GREEN. Release lines with no configured minimum produce no finding. |

The minimum-safe versions, the advisory note per release line, and the severity
(`info` / `warn` / `red`) all live in the `version:` block of the YAML config,
so they can be maintained as new advisories are published without a new build.

---

## Overriding thresholds

Every threshold ships as a conservative default meant to be quiet out of the
box. The right values depend on a cluster's normal volume, so any threshold can
be overridden per environment in a YAML config passed with `--config`.

[`examples/all-thresholds.yaml`](examples/all-thresholds.yaml) documents every
metric with its default. Copy it, keep only the lines you want to change, and
edit them. Common adjustments:

- **`relevance_floor`** — raise on a low-volume cluster to stay quiet; lower on
  a high-volume cluster so a smaller surge still registers.
- **`deviation`** — the multiple-of-baseline that counts as a spike. `3.0`
  suits a low-volume or newly-online cluster; during triage on a busy cluster a
  deviation as low as `1.5` can be significant.
- **`red` / `warn`** — the absolute thresholds for `absolute` and `or` metrics.

See the field legend at the top of the example file for the full set of
per-metric options.
