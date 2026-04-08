"""HTML renderer — self-contained HTML report."""

from __future__ import annotations

from jinja2 import Environment

from om_health_check.models import Report

_ENV = Environment(autoescape=True)

_TEMPLATE = _ENV.from_string("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OM Health Check Report</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
         background: #f5f5f5; color: #333; padding: 20px; }
  .report-header { background: #1a1a2e; color: #fff; padding: 20px; border-radius: 8px;
                   margin-bottom: 20px; }
  .report-header h1 { font-size: 1.4em; margin-bottom: 8px; }
  .report-header .meta { font-size: 0.85em; color: #aaa; }
  .cluster { background: #fff; border-radius: 8px; margin-bottom: 20px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }
  .cluster-header { padding: 16px 20px; border-bottom: 1px solid #eee;
                    display: flex; justify-content: space-between; align-items: center; }
  .cluster-header h2 { font-size: 1.1em; }
  .section { border-bottom: 1px solid #f0f0f0; }
  .section-header { padding: 12px 20px; background: #fafafa; cursor: pointer;
                    display: flex; justify-content: space-between; align-items: center;
                    font-weight: 600; font-size: 0.95em; }
  .section-header:hover { background: #f0f0f0; }
  .section-body { padding: 0 20px 12px; }
  .host-group { margin: 8px 0; }
  .host-label { font-size: 0.85em; color: #666; padding: 4px 0; font-weight: 600; }
  .check { display: flex; align-items: baseline; padding: 3px 0; font-size: 0.85em; }
  .check .badge { display: inline-block; width: 52px; text-align: center; font-size: 0.75em;
                  font-weight: 700; padding: 2px 6px; border-radius: 3px; margin-right: 8px;
                  flex-shrink: 0; }
  .check .name { font-weight: 600; margin-right: 6px; white-space: nowrap; }
  .check .msg { color: #555; }
  .badge.RED { background: #fee; color: #c0392b; }
  .badge.GREEN { background: #eafaf1; color: #27ae60; }
  .badge.WARN { background: #fef9e7; color: #f39c12; }
  .badge.INFO { background: #eaf2f8; color: #2980b9; }
  .status-pill { font-size: 0.8em; font-weight: 700; padding: 3px 10px;
                 border-radius: 12px; }
  .status-pill.RED { background: #c0392b; color: #fff; }
  .status-pill.GREEN { background: #27ae60; color: #fff; }
  .status-pill.WARN { background: #f39c12; color: #fff; }
  .status-pill.INFO { background: #2980b9; color: #fff; }
  details > summary { list-style: none; }
  details > summary::-webkit-details-marker { display: none; }
  details[open] .arrow { transform: rotate(90deg); }
  .arrow { display: inline-block; transition: transform 0.15s; margin-right: 6px; }
</style>
</head>
<body>
<div class="report-header">
  <h1>OM Health Check Report</h1>
  <div class="meta">
    Generated: {{ report.generated_at }} &nbsp;|&nbsp;
    Ops Manager: {{ report.om_url }} &nbsp;|&nbsp;
    Overall: <span class="status-pill {{ report.overall_status }}">{{ report.overall_status }}</span>
  </div>
</div>

{% for cr in report.clusters %}
<div class="cluster">
  <div class="cluster-header">
    <h2>{{ cr.cluster_name }} &mdash; {{ cr.project_name }}</h2>
    <span class="status-pill {{ cr.overall_status }}">{{ cr.overall_status }}</span>
  </div>

  {% for section in cr.sections %}
  <div class="section">
    <details{% if section.status == 'RED' %} open{% endif %}>
      <summary class="section-header">
        <span><span class="arrow">&#9654;</span> {{ section.name }}</span>
        <span class="status-pill {{ section.status }}">{{ section.status }}</span>
      </summary>
      <div class="section-body">
        {% for check in section.cluster_checks %}
        <div class="check">
          <span class="badge {{ check.status }}">{{ check.status }}</span>
          <span class="name">{{ check.name }}</span>
          <span class="msg">{{ check.message }}</span>
        </div>
        {% endfor %}

        {% for hs in section.hosts %}
        <div class="host-group">
          <div class="host-label">{{ hs.host }} ({{ hs.role }})</div>
          {% for check in hs.checks %}
          <div class="check">
            <span class="badge {{ check.status }}">{{ check.status }}</span>
            <span class="name">{{ check.name }}</span>
            <span class="msg">{{ check.message }}</span>
          </div>
          {% endfor %}
        </div>
        {% endfor %}
      </div>
    </details>
  </div>
  {% endfor %}
</div>
{% endfor %}

</body>
</html>
""")


def render(report: Report) -> str:
    return _TEMPLATE.render(report=report)
