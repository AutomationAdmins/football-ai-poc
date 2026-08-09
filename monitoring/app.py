"""
AI-Powered Monitoring Service for Football AI PoC.

Continuously polls GCP Cloud Logging for errors, uses Gemini to summarize
what's failing and why, and presents a clean monitoring dashboard.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import logging as cloud_logging
import google.generativeai as genai

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
_GEMINI_MODEL = "gemini-3.5-flash-lite"
_CLOUD_RUN_SERVICES = ["football-poc", "football-dashboard", "football-monitoring"]
_RESOURCE_TYPES = [
    "cloud_run_revision",
    "datastore_database",      # Firestore
    "gcs_bucket",              # Cloud Storage
    "pubsub_topic",            # Pub/Sub
    "pubsub_subscription",
    "cloud_build",             # Cloud Build
    "audited_resource",        # IAM / API errors
]

app = FastAPI(title="Football AI Monitoring")

# In-memory cache for summaries (reset on deploy)
_cache = {
    "last_summary": None,
    "last_errors": [],
    "last_check": None,
    "error_count_24h": 0,
    "healthy": True,
}


def _get_gemini_model():
    genai.configure(api_key=_GEMINI_KEY)
    return genai.GenerativeModel(_GEMINI_MODEL)


def _fetch_recent_logs(minutes: int = 30, severity: str = "ERROR") -> list[dict]:
    """Fetch recent error logs from all project services."""
    client = cloud_logging.Client(project=_PROJECT)
    
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=minutes)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    resource_filter = " OR ".join(
        f'resource.type="{rt}"' for rt in _RESOURCE_TYPES
    )
    
    filter_str = (
        f'({resource_filter}) '
        f'AND severity>={severity} '
        f'AND timestamp>="{since_str}" '
        f'AND NOT resource.labels.service_name="football-monitoring"'
    )
    
    entries = []
    for entry in client.list_entries(filter_=filter_str, order_by="timestamp desc", page_size=50):
        # Extract message from various payload formats
        if isinstance(entry.payload, str):
            payload = entry.payload
        elif isinstance(entry.payload, dict):
            payload = entry.payload.get("message") or entry.payload.get("textPayload") or json.dumps(entry.payload)
        else:
            payload = str(entry.payload) if entry.payload else ""
        # Also check http_request or insert_id for context
        if not payload and hasattr(entry, 'http_request') and entry.http_request:
            payload = f"{entry.http_request.get('requestMethod', '')} {entry.http_request.get('requestUrl', '')} → {entry.http_request.get('status', '')}"
        resource_type = entry.resource.type if entry.resource else "unknown"
        labels = entry.resource.labels if entry.resource else {}
        service = (
            labels.get("service_name")
            or labels.get("database_id")
            or labels.get("bucket_name")
            or labels.get("topic_id")
            or labels.get("subscription_id")
            or resource_type
        )
        entries.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
            "severity": entry.severity or "ERROR",
            "service": service,
            "resource_type": resource_type,
            "message": payload[:1500],
        })
    
    return entries


def _summarize_with_ai(errors: list[dict]) -> dict:
    """Use Groq LLM to produce a human-readable summary of errors."""
    if not errors:
        return {
            "status": "healthy",
            "summary": "No errors detected. All services running normally.",
            "issues": [],
            "recommendation": "System is healthy — no action needed.",
        }
    
    # Group errors by pattern
    error_texts = []
    for e in errors[:20]:  # Limit to 20 to fit in context
        error_texts.append(f"[{e['timestamp'][:19]}] {e['service']}: {e['message'][:400]}")
    
    prompt = f"""You are an AI ops engineer monitoring a live football insights system.

The system has these components:
- football-poc: FastAPI backend (Cloud Run) — receives Pub/Sub events, generates AI insights, stores in Firestore
- football-dashboard: Next.js frontend (Cloud Run) — displays live match insights
- football-monitoring: This monitoring service (Cloud Run)
- Firestore: Database storing insights, match_log, decisions, training_data
- GCS (football-poc-stats-avid): Stores historical player/team stats JSON
- Pub/Sub (opta-live-events): Ingests live match events
- Cloud Build: Builds and deploys container images

Here are the recent error logs (last 30 minutes):

{chr(10).join(error_texts)}

Analyze these errors and respond with JSON only:

{{
    "status": "critical" | "warning" | "degraded" | "healthy",
    "summary": "One sentence plain-English summary of what's wrong",
    "issues": [
        {{
            "title": "Short issue title",
            "cause": "What's causing this",
            "impact": "What users experience",
            "fix": "Suggested fix"
        }}
    ],
    "recommendation": "Top priority action to take right now",
    "error_pattern": "The most common error type seen"
}}

Be concise and actionable. Focus on root causes, not symptoms."""

    try:
        model = _get_gemini_model()
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                max_output_tokens=800,
            ),
        )
        raw = response.text.strip()
        
        # Extract JSON
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0:
            return json.loads(raw[start:end])
    except Exception as e:
        return {
            "status": "warning",
            "summary": f"Could not generate AI summary: {str(e)[:100]}",
            "issues": [{"title": "AI Summary Failed", "cause": str(e)[:200], "impact": "Manual log review needed", "fix": "Check GROQ_API_KEY"}],
            "recommendation": "Review logs manually in GCP Console.",
        }
    
    return {
        "status": "unknown",
        "summary": "Failed to parse AI response.",
        "issues": [],
        "recommendation": "Check logs manually.",
    }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "healthy", "service": "monitoring"}


@app.get("/api/status")
def get_status():
    """Get current monitoring status with AI summary."""
    try:
        errors = _fetch_recent_logs(minutes=30, severity="ERROR")
        warnings = _fetch_recent_logs(minutes=30, severity="WARNING")
        
        summary = _summarize_with_ai(errors)
        
        _cache["last_summary"] = summary
        _cache["last_errors"] = errors[:10]
        _cache["last_check"] = datetime.now(timezone.utc).isoformat()
        _cache["error_count_24h"] = len(errors)
        _cache["healthy"] = summary.get("status") == "healthy"
        
        return {
            "summary": summary,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "recent_errors": errors[:10],
            "last_check": _cache["last_check"],
            "services": _CLOUD_RUN_SERVICES,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "summary": {"status": "unknown", "summary": f"Monitoring failed: {str(e)[:200]}"},
        })


@app.get("/api/logs")
def get_logs(minutes: int = 60, severity: str = "ERROR"):
    """Get raw logs for a time window."""
    minutes = min(minutes, 1440)  # Cap at 24h
    logs = _fetch_recent_logs(minutes=minutes, severity=severity)
    return {"logs": logs, "count": len(logs), "window_minutes": minutes}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    """Monitoring dashboard UI."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Football AI — Monitoring</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
        .container { max-width: 1100px; margin: 0 auto; padding: 24px; }
        
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #21262d; }
        header h1 { font-size: 1.3rem; color: #f0f6fc; }
        .header-actions { display: flex; align-items: center; gap: 16px; }
        .live-badge { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; color: #8b949e; }
        .live-dot { width: 8px; height: 8px; background: #3fb950; border-radius: 50%; animation: pulse 2s infinite; }
        .live-dot--error { background: #f85149; }
        .live-dot--warning { background: #d29922; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        
        .btn { padding: 6px 12px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #c9d1d9; font-size: 0.75rem; cursor: pointer; transition: all 0.2s; }
        .btn:hover { background: #30363d; border-color: #8b949e; }
        .btn--active { background: #58a6ff; color: #0d1117; border-color: #58a6ff; }
        
        .status-card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        .status-card--critical { border-color: #f85149; background: linear-gradient(135deg, #1a0a0a 0%, #161b22 100%); }
        .status-card--warning { border-color: #d29922; }
        .status-card--healthy { border-color: #3fb950; }
        .status-card--degraded { border-color: #a371f7; }
        
        .status-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
        .status-badge { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
        .status-badge--critical { background: #f85149; color: white; }
        .status-badge--warning { background: #d29922; color: #0d1117; }
        .status-badge--healthy { background: #3fb950; color: #0d1117; }
        .status-badge--degraded { background: #a371f7; color: white; }
        
        .summary-text { font-size: 1.1rem; color: #f0f6fc; font-weight: 500; line-height: 1.5; }
        .recommendation { margin-top: 12px; padding: 12px; background: #21262d; border-radius: 8px; font-size: 0.9rem; color: #8b949e; }
        .recommendation strong { color: #58a6ff; }
        
        .issues-list { list-style: none; margin-top: 16px; }
        .issue-item { padding: 12px; border: 1px solid #21262d; border-radius: 8px; margin-bottom: 8px; cursor: pointer; transition: all 0.2s; }
        .issue-item:hover { border-color: #58a6ff; background: #1c2128; }
        .issue-item--expanded { background: #1c2128; border-color: #30363d; }
        .issue-title { color: #f0f6fc; font-weight: 600; font-size: 0.9rem; margin-bottom: 4px; }
        .issue-detail { font-size: 0.8rem; color: #8b949e; line-height: 1.6; display: none; }
        .issue-item--expanded .issue-detail { display: block; margin-top: 8px; }
        .issue-detail span { display: block; margin-top: 4px; }
        .issue-fix { color: #3fb950; }
        
        .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
        .stat-box { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 16px; text-align: center; cursor: pointer; transition: all 0.2s; }
        .stat-box:hover { border-color: #58a6ff; transform: translateY(-1px); }
        .stat-box--active { border-color: #58a6ff; background: #1c2128; }
        .stat-number { font-size: 1.8rem; font-weight: 700; color: #f0f6fc; }
        .stat-number--error { color: #f85149; }
        .stat-number--warning { color: #d29922; }
        .stat-number--ok { color: #3fb950; }
        .stat-label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
        
        .filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
        
        .log-section { margin-top: 20px; }
        .log-section h3 { font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
        .log-count { background: #21262d; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; }
        
        .log-entry { font-family: 'SF Mono', monospace; font-size: 0.78rem; padding: 10px 14px; border-left: 3px solid #f85149; background: #161b22; margin-bottom: 4px; border-radius: 0 6px 6px 0; line-height: 1.4; cursor: pointer; transition: all 0.15s; }
        .log-entry:hover { background: #1c2128; border-left-color: #58a6ff; }
        .log-entry--warning { border-left-color: #d29922; }
        .log-entry--expanded { background: #1c2128; white-space: pre-wrap; word-break: break-all; }
        .log-header { display: flex; align-items: center; gap: 10px; }
        .log-time { color: #6e7681; min-width: 65px; }
        .log-svc { color: #58a6ff; font-weight: 600; min-width: 140px; }
        .log-resource { color: #a371f7; font-size: 0.7rem; }
        .log-preview { color: #c9d1d9; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
        .log-full { display: none; margin-top: 10px; padding: 10px; background: #0d1117; border-radius: 6px; white-space: pre-wrap; word-break: break-all; color: #f0f6fc; font-size: 0.72rem; max-height: 300px; overflow-y: auto; border: 1px solid #21262d; }
        .log-entry--expanded .log-full { display: block; }
        .log-entry--expanded .log-preview { display: none; }
        
        .refresh-info { text-align: center; color: #6e7681; font-size: 0.75rem; margin-top: 20px; display: flex; justify-content: center; align-items: center; gap: 12px; }
        .loading { text-align: center; padding: 60px; color: #8b949e; }
        
        .tab-bar { display: flex; gap: 4px; margin-bottom: 20px; background: #161b22; padding: 4px; border-radius: 8px; border: 1px solid #21262d; }
        .tab { padding: 8px 16px; border-radius: 6px; font-size: 0.8rem; cursor: pointer; color: #8b949e; transition: all 0.2s; }
        .tab:hover { color: #c9d1d9; }
        .tab--active { background: #21262d; color: #f0f6fc; font-weight: 600; }
        
        .empty-state { text-align: center; padding: 40px; color: #6e7681; font-size: 0.9rem; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>🔍 Football AI — System Monitor</h1>
        <div class="header-actions">
            <button class="btn" onclick="fetchStatus()" title="Refresh now">↻ Refresh</button>
            <div class="live-badge">
                <div class="live-dot" id="status-dot"></div>
                <span id="status-text">Checking...</span>
            </div>
        </div>
    </header>
    
    <div id="content"><div class="loading">Fetching logs and generating AI summary...</div></div>
</div>

<script>
let currentData = null;
let activeFilter = null;
let activeTab = 'errors';
let expandedLogs = new Set();

async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        currentData = data;
        render(data);
    } catch(e) {
        document.getElementById('content').innerHTML = '<div class="status-card status-card--critical"><div class="summary-text">Failed to fetch monitoring data: ' + e.message + '</div></div>';
    }
}

async function fetchLogs(severity, minutes) {
    try {
        const res = await fetch('/api/logs?severity=' + severity + '&minutes=' + (minutes || 60));
        const data = await res.json();
        return data.logs || [];
    } catch(e) {
        return [];
    }
}

function toggleLog(idx) {
    if (expandedLogs.has(idx)) expandedLogs.delete(idx);
    else expandedLogs.add(idx);
    render(currentData);
}

function toggleIssue(el) {
    el.classList.toggle('issue-item--expanded');
}

function setFilter(svc) {
    activeFilter = activeFilter === svc ? null : svc;
    render(currentData);
}

function setTab(tab) {
    activeTab = tab;
    expandedLogs.clear();
    render(currentData);
}

function render(data) {
    const s = data.summary || {};
    const status = s.status || 'unknown';
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    
    dot.className = 'live-dot' + (status === 'healthy' ? '' : status === 'warning' ? ' live-dot--warning' : ' live-dot--error');
    statusText.textContent = status.toUpperCase() + ' — Auto-refreshing every 30s';
    
    let html = '';
    
    // Stats row
    html += '<div class="stats-row">';
    html += '<div class="stat-box" onclick="setTab(\\'errors\\')"><div class="stat-number ' + (data.error_count > 0 ? 'stat-number--error' : 'stat-number--ok') + '">' + (data.error_count || 0) + '</div><div class="stat-label">Errors (30min)</div></div>';
    html += '<div class="stat-box" onclick="setTab(\\'warnings\\')"><div class="stat-number stat-number--warning">' + (data.warning_count || 0) + '</div><div class="stat-label">Warnings (30min)</div></div>';
    html += '<div class="stat-box"><div class="stat-number stat-number--ok">' + (data.services?.length || 0) + '</div><div class="stat-label">Services</div></div>';
    
    // Count unique services in errors
    const svcSet = new Set((data.recent_errors || []).map(e => e.service));
    html += '<div class="stat-box"><div class="stat-number">' + svcSet.size + '</div><div class="stat-label">Affected Services</div></div>';
    html += '</div>';
    
    // AI Summary card
    html += '<div class="status-card status-card--' + status + '">';
    html += '<div class="status-header"><span class="status-badge status-badge--' + status + '">' + status + '</span><span style="color:#8b949e;font-size:0.8rem">AI Analysis (Gemini)</span></div>';
    html += '<div class="summary-text">' + (s.summary || 'No summary available') + '</div>';
    
    if (s.recommendation) {
        html += '<div class="recommendation"><strong>→ Action:</strong> ' + s.recommendation + '</div>';
    }
    
    if (s.issues && s.issues.length > 0) {
        html += '<ul class="issues-list">';
        s.issues.forEach(issue => {
            html += '<li class="issue-item" onclick="toggleIssue(this)">';
            html += '<div class="issue-title">⚠️ ' + (issue.title || '') + ' <span style="font-size:0.7rem;color:#6e7681">▸ click to expand</span></div>';
            html += '<div class="issue-detail">';
            if (issue.cause) html += '<span><b>Cause:</b> ' + issue.cause + '</span>';
            if (issue.impact) html += '<span><b>Impact:</b> ' + issue.impact + '</span>';
            if (issue.fix) html += '<span class="issue-fix"><b>Fix:</b> ' + issue.fix + '</span>';
            html += '</div></li>';
        });
        html += '</ul>';
    }
    html += '</div>';
    
    // Service filter pills
    const allServices = [...new Set((data.recent_errors || []).map(e => e.service))];
    if (allServices.length > 0) {
        html += '<div class="filters">';
        html += '<button class="btn ' + (!activeFilter ? 'btn--active' : '') + '" onclick="setFilter(null)">All</button>';
        allServices.forEach(svc => {
            html += '<button class="btn ' + (activeFilter === svc ? 'btn--active' : '') + '" onclick="setFilter(\\'' + svc + '\\')">' + svc + '</button>';
        });
        html += '</div>';
    }
    
    // Log entries
    let logs = data.recent_errors || [];
    if (activeFilter) {
        logs = logs.filter(l => l.service === activeFilter);
    }
    
    if (logs.length > 0) {
        html += '<div class="log-section"><h3>Recent Errors <span class="log-count">' + logs.length + '</span></h3>';
        logs.forEach((log, idx) => {
            const time = log.timestamp ? log.timestamp.substring(11, 19) : '';
            const msg = (log.message || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            const preview = msg.substring(0, 120);
            const expanded = expandedLogs.has(idx);
            
            html += '<div class="log-entry ' + (expanded ? 'log-entry--expanded' : '') + '" onclick="toggleLog(' + idx + ')">';
            html += '<div class="log-header">';
            html += '<span class="log-time">' + time + '</span>';
            html += '<span class="log-svc">[' + (log.service || 'unknown') + ']</span>';
            if (log.resource_type && log.resource_type !== 'cloud_run_revision') html += '<span class="log-resource">' + log.resource_type + '</span>';
            html += '<span class="log-preview">' + preview + '</span>';
            html += '</div>';
            html += '<div class="log-full">' + msg + '</div>';
            html += '</div>';
        });
        html += '</div>';
    } else {
        html += '<div class="empty-state">No errors to show' + (activeFilter ? ' for ' + activeFilter : '') + '</div>';
    }
    
    html += '<div class="refresh-info"><span>Last check: ' + (data.last_check ? new Date(data.last_check).toLocaleTimeString() : 'now') + '</span><span>·</span><span>Refreshes every 30 seconds</span></div>';
    
    document.getElementById('content').innerHTML = html;
}

fetchStatus();
setInterval(fetchStatus, 30000);
</script>
</body>
</html>"""
