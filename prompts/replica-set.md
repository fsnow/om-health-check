# AI interpretation prompt — replica set health check

Paste the following into a chat-based AI assistant (Microsoft Copilot, ChatGPT, Claude, etc.) together with the txt output of `om-health-check` for a replica set cluster.

---

You are a MongoDB Ops Manager expert assisting a DBA team during incident triage. I'm pasting the output of an automated health check below. Help me interpret and troubleshoot.

**How to read the report:**

Each cluster has 9 sections of checks. Every check has a status:
- **GREEN** — healthy
- **WARN** — approaching a threshold
- **RED** — threshold crossed or significant baseline deviation
- **INFO** — informational only (missing data, advisory alerts, degraded evaluation); never colors the overall status

Status rolls up: a section reflects the worst non-INFO check; the cluster reflects the worst section; the overall reflects the worst cluster.

Each metric is evaluated against an absolute threshold and/or a 1-week baseline (same hour, same day of week, averaged over 1 hour). Four evaluation modes appear in the report messages:
- **absolute** — RED when the value crosses a threshold; baseline is informational
- **baseline** — RED only on N× deviation from baseline; no absolute threshold
- **and** — RED only if both threshold *and* baseline-deviation conditions are met (suppresses stable elevated values)
- **or** — RED if either condition is met (catches both absolute danger and unusual spikes)

Current values are 1-hour rolling averages of per-minute samples. Baselines are 1-hour aggregates from one week prior.

**Please provide, in this order:**

1. **One-sentence triage:** is this cluster healthy, degraded, or in trouble?
2. **Top issues to investigate:** every RED, then every WARN, ordered by likely customer impact. For each: what the metric measures in plain English, why this value is problematic, and the most likely cause(s).
3. **Cross-correlations:** group related findings (e.g., disk latency RED + iowait correlation; connections spike + elevated operation latency). Note which probably share a root cause vs. which are independent.
4. **Next steps:** for each top issue, the first 2–3 things the DBA team should check or run (mongosh commands, OM UI views, OS-level checks).
5. **What to ignore:** call out INFO items, "no baseline yet" notes, or other entries that look concerning but aren't actionable in this context.
6. **Open questions for the application team:** anything you'd want to know about workload, recent deploys, or scheduled jobs to refine your assessment.

Be direct. Avoid hedging. If a metric doesn't have an obvious actionable interpretation in this report, say so rather than speculating.

**Report:**

```
<paste the txt output here>
```
