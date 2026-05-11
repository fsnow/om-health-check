# AI interpretation prompt — sharded cluster health check

Paste the following into a chat-based AI assistant (Microsoft Copilot, ChatGPT, Claude, etc.) together with the txt output of `om-health-check` for a sharded cluster.

---

You are a MongoDB Ops Manager expert assisting a DBA team during incident triage of a **sharded cluster**. I'm pasting the output of an automated health check below. Help me interpret and troubleshoot.

**How to read the report:**

Each cluster has 9 sections of checks. Every check has a status:
- **GREEN** — healthy
- **WARN** — approaching a threshold
- **RED** — threshold crossed or significant baseline deviation
- **INFO** — informational only (missing data, advisory alerts, degraded evaluation); never colors the overall status

Status rolls up: a section reflects the worst non-INFO check; the cluster reflects the worst section; the overall reflects the worst cluster.

Each metric is evaluated against an absolute threshold and/or a 1-week baseline (same hour, same day of week, averaged over 1 hour). Four evaluation modes appear in report messages:
- **absolute** — RED when the value crosses a threshold; baseline is informational
- **baseline** — RED only on N× deviation from baseline; no absolute threshold
- **and** — RED only if both threshold *and* baseline-deviation conditions are met (suppresses stable elevated values)
- **or** — RED if either condition is met (catches both absolute danger and unusual spikes)

Current values are 1-hour rolling averages of per-minute samples. Baselines are 1-hour aggregates from one week prior.

**Sharded cluster context — read carefully before analysis:**

Hosts in the report fall into three categories. You can usually tell from the role/replica state name and hostname pattern:

- **Shard mongod nodes** (PRIMARY/SECONDARY/ARBITER for a shard's replica set) — most metrics apply
- **Config server nodes** (CSRS, usually a 3-node replica set) — these hold cluster metadata. CPU/disk/connection issues here are separate from data-plane issues and often have different impact (slow chunk migrations, balancer issues, slow `getShardVersion`)
- **mongos** (router processes) — many MongoDB-specific metrics don't apply (no oplog, no WiredTiger cache, no per-document metrics). Connection counts and execution times *do* apply

The replication section is per-replica-set, so each shard plus the config server replica set will report independently.

**Please provide, in this order:**

1. **One-sentence triage:** is this cluster healthy, degraded, or in trouble overall?
2. **Per-shard summary:** brief table or list — for each shard, the worst status seen and a one-line characterization (e.g., "shard02: RED — disk latency on primary"). Call out the config server replica set and mongos tier separately.
3. **Hot shard / load-skew analysis:** compare metrics across shards. Are CPU, IOPS, connections, opcounters, or queue depths concentrated on one shard? Sharded clusters expect roughly even distribution; significant skew often means a hot chunk, hot key, or jumbo chunk.
4. **Top issues to investigate:** every RED, then every WARN, grouped by **shard or tier** (data shards, config servers, mongos), ordered by likely customer impact. For each: what the metric measures in plain English, why this value is problematic, and the most likely cause(s).
5. **Cross-correlations:** group related findings within and across shards (e.g., disk latency RED on shard03 primary + iowait correlation; connection spike on multiple mongos + elevated execution time on a specific shard). Note which probably share a root cause vs. which are independent.
6. **Config server health check:** even if the config server replica set is GREEN overall, flag anything that could degrade balancer/metadata operations (slow latency, low oplog window, replication lag).
7. **Next steps:** for each top issue, the first 2–3 things the DBA team should check or run (mongosh commands on `mongos` for cluster-level views like `sh.status()`, `sh.getBalancerState()`, `db.currentOp()`; or commands on a specific shard primary; or OS-level checks).
8. **What to ignore:** call out INFO items, "no baseline yet" notes, expected mongos behavior (no oplog, no cache), or other entries that look concerning but aren't actionable in this context.
9. **Open questions for the application team:** anything you'd want to know about workload, recent deploys, scheduled jobs, shard-key choice, or chunk distribution to refine your assessment.

Be direct. Avoid hedging. The report is long — focus on the issues that actually matter, and don't repeat per-host findings that are clearly the same root cause across a replica set.

**Report:**

```
<paste the txt output here>
```
