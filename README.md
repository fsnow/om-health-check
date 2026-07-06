# om-health-check

A CLI tool that queries the MongoDB Ops Manager API to produce a structured health assessment of MongoDB clusters. Designed for use during incidents and proactive health checks.

## What it does

Runs 9 categories of checks against one or more clusters via the Ops Manager API:

1. **Connectivity & Infrastructure** — API reachability, node status, agent status, active alerts, network throughput
2. **Compute Resources** — CPU (user, iowait, process), memory, swap; deeper CPU breakdown when issues detected
3. **Disk Resources** — read/write latency, IOPS, partition space, iowait correlation
4. **Cache Resources** — WiredTiger cache used bytes, dirty bytes, cache read/write rates
5. **Database Activity & Workload** — query targeting, scan and order, opcounters, document metrics, execution times, global lock queues, Performance Advisor
6. **Replication** — replication lag, oplog window, oplog rate
7. **Connections** — connection count, zero-connection detection, connection storm correlation
8. **Backup** — backup config status, snapshot schedule adherence, capture lag
9. **Version Information** — version consistency across nodes, known-bad version detection (CVEs)

Each metric is compared against both an absolute threshold and a 1-week baseline (same day-of-week, same hour) to reduce false positives from normal workload variance.

## Installation

```bash
pip install om-health-check
```

Requires Python 3.9+.

## API key permissions

The API key must have the **Project Read Only** role on each project being checked. This provides read access to deployments, measurements, alerts, agents, and backup status — covering 8 of the 9 check sections.

No write permissions are required. The tool never modifies any Ops Manager configuration.

### Performance Advisor section — additional role required

The **Performance Advisor** section calls endpoints that require the **Project Data Access Read Only** role (or higher). Per the [Ops Manager docs](https://www.mongodb.com/docs/ops-manager/current/reference/api/performance-advisor/), the allowed roles are: Project Owner, Project Data Access Admin, Project Data Access Read/Write, or Project Data Access Read Only.

The minimum role granting this access (Project Data Access Read Only) also grants the holder read access to database contents. There is no narrower read-only-observability role for Performance Advisor in Ops Manager.

For security-conscious deployments where most personnel should not have database read access, run the tool with a **Project Read Only** key. The Performance Advisor section will report an INFO message — *"Performance Advisor access denied — requires Project Data Access Read Only role or higher"* — and the other 8 sections work normally. To minimize API load when access is denied, the script makes only one Performance Advisor call per cluster and reuses the message for the remaining hosts.

If the API key lacks sufficient permissions, affected checks report a clear message indicating which permission is missing rather than failing the whole report.

## Usage

```bash
export OPS_MANAGER_USER=your-public-key
export OPS_MANAGER_API_KEY=your-private-key

om-health-check --om-url https://ops-manager.example.com --project "My Project"
```

### Options

| Flag | Required | Description |
|---|---|---|
| `--om-url` | Yes | Ops Manager base URL |
| `--project` | Yes | Project name (repeatable for multiple projects) |
| `--cluster` | No | Cluster name filter; omit to check all clusters in the project(s) |
| `--format` | No | `txt` (default), `json`, `html`, or comma-separated (e.g. `txt,html`) |
| `--config` | No | Path to YAML config file for threshold overrides |

### Output formats

- **txt** — plain text, suitable for pasting into incident tickets
- **json** — machine-readable, for downstream tooling or dashboards
- **html** — self-contained HTML with color-coded status and collapsible sections

### Examples

Check all clusters in a project:
```bash
om-health-check --om-url https://om.example.com --project "Production"
```

Check a specific cluster across two projects, output as text and HTML:
```bash
om-health-check --om-url https://om.example.com \
  --project "Production" --project "Staging" \
  --cluster "rs0" \
  --format txt,html
```

## Threshold configuration

Every metric has a default threshold. To override defaults, create a YAML config file.

The tool looks for config in this order:
1. Path passed via `--config`
2. `OM_HEALTH_CHECK_CONFIG` environment variable
3. `~/.om-health-check.yaml`

Only metrics you want to change need to be specified. Unspecified fields retain their defaults.

```yaml
thresholds:
  CONNECTIONS:
    red: 30000
    warn: 25000
  SYSTEM_NORMALIZED_CPU_USER:
    red: 90.0
    mode: "or"
  DISK_PARTITION_LATENCY_READ:
    red: 15.0
    warn: 8.0
```

See [`examples/all-thresholds.yaml`](examples/all-thresholds.yaml) for a reference file listing every metric with its built-in defaults — copy, subset, and edit to produce a custom config.

See [`examples/low-thresholds.yaml`](examples/low-thresholds.yaml) for a smoke-test config with aggressively low thresholds designed to trigger RED on a healthy cluster — useful for verifying the tool runs end-to-end.

### Threshold fields

| Field | Type | Description |
|---|---|---|
| `red` | float | Value that triggers RED status |
| `warn` | float | Value that triggers WARN status |
| `direction` | string | `"above"` (RED when value >= red) or `"below"` (RED when value <= red) |
| `deviation` | float | Baseline multiplier (e.g. `3.0` = RED if current >= 3x baseline) |
| `relevance_floor` | float | Gate on the deviation check — ignored unless the current value is past this absolute floor (>= it for `above` metrics, <= it for `below`). Suppresses "3x of a tiny number" noise. Omit for no floor. |
| `mode` | string | How threshold and baseline interact (see below) |

### Evaluation modes

| Mode | Behavior |
|---|---|
| `absolute` | RED if value crosses threshold. Baseline is informational. |
| `baseline` | RED only if value deviates from baseline by the configured multiplier. No absolute threshold. |
| `and` | RED only if value crosses threshold AND deviates from baseline. Suppresses false positives from stable elevated values. |
| `or` | RED if value crosses threshold OR deviates from baseline. Catches both absolute danger and unusual spikes. |

## Baseline comparison

Current metric values are compared against the same hour, same day of week, one week prior. This accounts for recurring workload patterns (business hours vs nights vs weekends) and avoids flagging normal variance as anomalous.

**Current values** are fetched at PT1M granularity over the past hour and averaged, producing a 1-hour rolling average. This sidesteps Ops Manager's mid-hour PT1H rollup, which is not yet populated for rate-based metrics (CPU %, network bytes/sec) until the hour boundary.

**Baseline values** are fetched at PT1H granularity from the 1-hour window one week ago. Ops Manager retains hourly data for 2 months by default.

Comparing two hourly averages keeps the check apples-to-apples and resistant to single-minute spikes.

### Graceful degradation when data is missing

The tool is resilient to gaps in OM data:

- **No current data available** → reported as INFO (e.g., no read activity means no `DISK_PARTITION_LATENCY_READ` sample)
- **No baseline data available** (cluster is less than 1 week old) → behavior depends on evaluation mode:
  - `absolute` — works unchanged (baseline is informational)
  - `baseline` — reports INFO with the current value and "no baseline yet (cluster < 1 week old)"
  - `and` / `or` — degrades to threshold-only evaluation, with a "no baseline yet" note appended to the message
- **Metric not exposed by the OM API version** → batched fetch falls back to per-metric calls; unavailable metrics are summarized once on stderr

## Status rollup

Each check produces one of four statuses:

- `GREEN` — healthy
- `WARN` — approaching threshold
- `RED` — threshold crossed or baseline significantly deviated
- `INFO` — informational only (missing data, advisory alerts, degraded evaluation)

Section, cluster, and overall status roll up the worst status among their children — **with one important rule: `INFO` never bubbles up**. A cluster with only INFO items still reports overall GREEN. This keeps the headline color honest about operational health without hiding informational details.

Certain advisory alerts (e.g., `HOST_SECURITY_CHECKUP_NOT_MET`, which commonly fires as a false positive for deployments using external auth like LDAP) are classified as INFO so they are visible but do not color the overall report.

## Monitoring agents

Ops Manager uses leader election for monitoring agents: exactly one agent per project is `ACTIVE`, the rest are `STANDBY` (ready to take over if the active agent fails). The tool reports a single GREEN "Agent status" check when at least one agent is ACTIVE, and RED only if no ACTIVE agent exists (which means monitoring data is not being collected).

## Dependencies

- [opsmanager](https://pypi.org/project/opsmanager/) — Ops Manager API client
- [Jinja2](https://pypi.org/project/Jinja2/) — HTML report templating
- [packaging](https://pypi.org/project/packaging/) — version comparison
- [PyYAML](https://pypi.org/project/PyYAML/) — config file parsing

## License

Apache 2.0
