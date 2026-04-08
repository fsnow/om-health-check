# om-health-check

A CLI tool that queries the MongoDB Ops Manager API to produce a structured health assessment of MongoDB clusters. Designed for use during incidents and proactive health checks.

## What it does

Runs 9 categories of checks against one or more clusters via the Ops Manager API:

1. **Connectivity & Infrastructure** — API reachability, node status, agent status, active alerts, host restarts, network throughput
2. **Compute Resources** — CPU (user, iowait, process), memory, swap; deeper CPU breakdown when issues detected
3. **Disk Resources** — read/write latency, IOPS, partition space, queue depth, iowait correlation
4. **Cache Resources** — WiredTiger cache fill ratio, dirty ratio, cache read/write rates
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

Requires Python 3.10+.

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

### Threshold fields

| Field | Type | Description |
|---|---|---|
| `red` | float | Value that triggers RED status |
| `warn` | float | Value that triggers WARN status |
| `direction` | string | `"above"` (RED when value >= red) or `"below"` (RED when value <= red) |
| `deviation` | float | Baseline multiplier (e.g. `3.0` = RED if current >= 3x baseline) |
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

Granularity is PT1H (hourly averages). Ops Manager retains hourly data for 2 months by default.

## Dependencies

- [python-mongodb-ops-manager](https://pypi.org/project/opsmanager/) — Ops Manager API client
- [Jinja2](https://pypi.org/project/Jinja2/) — HTML report templating
- [packaging](https://pypi.org/project/packaging/) — version comparison
- [PyYAML](https://pypi.org/project/PyYAML/) — config file parsing

## License

Apache 2.0
