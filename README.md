# om-health-check

A CLI tool that queries the MongoDB Ops Manager API to produce a structured health assessment of MongoDB clusters. Designed for use during incidents and proactive health checks.

## What it does

Runs 10 categories of checks against one or more clusters via the Ops Manager API:

1. **Connectivity & Infrastructure** — API reachability, node status, agent status, active alerts, network throughput
2. **Compute Resources** — CPU (user, iowait, process), memory, swap; deeper CPU breakdown when issues detected
3. **Disk Resources** — read/write latency, IOPS, partition space, iowait correlation
4. **Cache Resources** — WiredTiger cache used bytes, dirty bytes, cache read/write rates
5. **Database Activity & Workload** — query targeting, scan and order, opcounters, document metrics, execution times, global lock queues, Performance Advisor
6. **Oplog** — oplog window (`OPLOG_MASTER_TIME`) and oplog write rate, per replica-set member
7. **Replication** — secondary replication lag behind the primary
8. **Connections** — connection count, zero-connection detection, connection storm correlation
9. **Backup** — backup config status, in-progress snapshot, snapshot schedule adherence, capture lag
10. **Version Information** — version consistency across nodes, and version currency against configurable minimum-safe versions (INFO by default)

Each metric is compared against both an absolute threshold and a 1-week baseline (same day-of-week, same hour) to reduce false positives from normal workload variance.

See **[METRICS.md](METRICS.md)** for a full reference: every metric, what it measures, its units, and the exact status criteria.

## Installation

```bash
pip install om-health-check
```

Requires Python 3.9+.

## API key permissions

The API key must have the **Project Read Only** role on each project being checked. This provides read access to deployments, measurements, alerts, agents, and backup status — covering everything except the Performance Advisor portion of the Database Activity & Workload section.

No write permissions are required. The tool never modifies any Ops Manager configuration.

### Performance Advisor section — additional role required

The **Performance Advisor** section calls endpoints that require the **Project Data Access Read Only** role (or higher). Per the [Ops Manager docs](https://www.mongodb.com/docs/ops-manager/current/reference/api/performance-advisor/), the allowed roles are: Project Owner, Project Data Access Admin, Project Data Access Read/Write, or Project Data Access Read Only.

The minimum role granting this access (Project Data Access Read Only) also grants the holder read access to database contents. There is no narrower read-only-observability role for Performance Advisor in Ops Manager.

For security-conscious deployments where most personnel should not have database read access, run the tool with a **Project Read Only** key. The Performance Advisor check will report an INFO message — *"Performance Advisor access denied — requires Project Data Access Read Only role or higher"* — and the rest of the report works normally. To minimize API load when access is denied, the script makes only one Performance Advisor call per cluster and reuses the message for the remaining hosts.

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

For the threshold fields and the evaluation-mode semantics, see the field legend at the top of [`examples/all-thresholds.yaml`](examples/all-thresholds.yaml).

## How checks are evaluated

Statuses (GREEN / WARN / RED / INFO), the roll-up rule (**INFO never colors the overall status**), baseline windowing, the evaluation modes, and the relevance floor are all documented in **[METRICS.md](METRICS.md)**, alongside the exact criteria for every metric.

One operational note not covered there: if a metric is not exposed by the running Ops Manager API version, the batched fetch falls back to per-metric calls and the unavailable metrics are summarized once on stderr.

## Dependencies

- [opsmanager](https://pypi.org/project/opsmanager/) — Ops Manager API client
- [Jinja2](https://pypi.org/project/Jinja2/) — HTML report templating
- [packaging](https://pypi.org/project/packaging/) — version comparison
- [PyYAML](https://pypi.org/project/PyYAML/) — config file parsing

## License

Apache 2.0
