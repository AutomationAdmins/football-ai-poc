"""
AI-Powered Monitoring Service for Football AI PoC.

Continuously polls GCP Cloud Logging for errors, uses Groq LLM to summarize
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
from openai import OpenAI

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")
_GROQ_KEY = os.environ.get("GROQ_API_KEY")
_GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_SERVICES = ["football-poc", "football-dashboard"]

app = FastAPI(title="Football AI Monitoring")

# In-memory cache for summaries (reset on deploy)
_cache = {
    "last_summary": None,
    "last_errors": [],
    "last_check": None,
    "error_count_24h": 0,
    "healthy": True,
}


def _get_groq_client():
    return OpenAI(api_key=_GROQ_KEY, base_url="https://api.groq.com/openai/v1")


def _fetch_recent_logs(minutes: int = 30, severity: str = "ERROR") -> list[dict]:
    """Fetch recent error logs from Cloud Run services."""
    client = cloud_logging.Client(project=_PROJECT)
    
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=minutes)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    services_filter = " OR ".join(
        f'resource.labels.service_name="{svc}"' for svc in _SERVICES
    )
    
    filter_str = (
        f'resource.type="cloud_run_revision" '
        f'AND ({services_filter}) '
        f'AND severity>={severity} '
        f'AND timestamp>="{since_str}"'
    )
    
    entries = []
    for entry in client.list_entries(filter_=filter_str, order_by="timestamp desc", page_size=50):
        payload = entry.payload if isinstance(entry.payload, str) else json.dumps(entry.payload) if entry.payload else ""
        entries.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
            "severity": entry.severity or "ERROR",
            "service": entry.resource.labels.get("service_name", "unknown") if entry.resource else "unknown",
            "revision": entry.resource.labels.get("revision_name", "") if entry.resource else "",
            "message": payload[:1500],  # Truncate long tracebacks
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
- football-poc: FastAPI backend that receives Pub/Sub events, generates AI insights, stores in Firestore
- football-dashboard: Next.js frontend that displays live match insights

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
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_GROQ_MODEL,
            temperature=0,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        
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
            "services": _SERVICES,
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
        .container { max-width: 900px; margin: 0 auto; padding: 24px; }
        
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #21262d; }
        header h1 { font-size: 1.3rem; color: #f0f6fc; }
        .live-badge { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; color: #8b949e; }
        .live-dot { width: 8px; height: 8px; background: #3fb950; border-radius: 50%; animation: pulse 2s infinite; }
        .live-dot--error { background: #f85149; }
        .live-dot--warning { background: #d29922; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        
        .status-card { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
        .status-card--critical { border-color: #f85149; background: linear-gradient(135deg, #1a0a0a 0%, #161b22 100%); }
        .status-card--warning { border-color: #d29922; }
        .status-card--healthy { border-color: #3fb950; }
        
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
        .issue-item { padding: 12px; border: 1px solid #21262d; border-radius: 8px; margin-bottom: 8px; }
        .issue-title { color: #f0f6fc; font-weight: 600; font-size: 0.9rem; margin-bottom: 4px; }
        .issue-detail { font-size: 0.8rem; color: #8b949e; line-height: 1.4; }
        .issue-detail span { display: block; margin-top: 2px; }
        .issue-fix { color: #3fb950; }
        
        .stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
        .stat-box { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 16px; text-align: center; }
        .stat-number { font-size: 1.8rem; font-weight: 700; color: #f0f6fc; }
        .stat-number--error { color: #f85149; }
        .stat-number--ok { color: #3fb950; }
        .stat-label { font-size: 0.75rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
        
        .log-section { margin-top: 20px; }
        .log-section h3 { font-size: 0.85rem; color: #8b949e; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
        .log-entry { font-family: 'SF Mono', monospace; font-size: 0.75rem; padding: 8px 12px; border-left: 3px solid #f85149; background: #161b22; margin-bottom: 4px; border-radius: 0 4px 4px 0; line-height: 1.4; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .log-entry:hover { white-space: normal; }
        .log-time { color: #6e7681; }
        .log-svc { color: #58a6ff; }
        
        .refresh-info { text-align: center; color: #6e7681; font-size: 0.75rem; margin-top: 20px; }
        .loading { text-align: center; padding: 60px; color: #8b949e; }
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>🔍 Football AI — System Monitor</h1>
        <div class="live-badge">
            <div class="live-dot" id="status-dot"></div>
            <span id="status-text">Checking...</span>
        </div>
    </header>
    
    <div id="content"><div class="loading">Fetching logs and generating AI summary...</div></div>
</div>

<script>
async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        render(data);
    } catch(e) {
        document.getElementById('content').innerHTML = '<div class="status-card status-card--critical"><div class="summary-text">Failed to fetch monitoring data: ' + e.message + '</div></div>';
    }
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
    html += '<div class="stat-box"><div class="stat-number ' + (data.error_count > 0 ? 'stat-number--error' : 'stat-number--ok') + '">' + (data.error_count || 0) + '</div><div class="stat-label">Errors (30min)</div></div>';
    html += '<div class="stat-box"><div class="stat-number">' + (data.warning_count || 0) + '</div><div class="stat-label">Warnings (30min)</div></div>';
    html += '<div class="stat-box"><div class="stat-number stat-number--ok">' + (data.services?.length || 0) + '</div><div class="stat-label">Services Monitored</div></div>';
    html += '</div>';
    
    // AI Summary card
    html += '<div class="status-card status-card--' + status + '">';
    html += '<div class="status-header"><span class="status-badge status-badge--' + status + '">' + status + '</span><span style="color:#8b949e;font-size:0.8rem">AI Analysis</span></div>';
    html += '<div class="summary-text">' + (s.summary || 'No summary available') + '</div>';
    
    if (s.recommendation) {
        html += '<div class="recommendation"><strong>→ Action:</strong> ' + s.recommendation + '</div>';
    }
    
    if (s.issues && s.issues.length > 0) {
        html += '<ul class="issues-list">';
        s.issues.forEach(issue => {
            html += '<li class="issue-item">';
            html += '<div class="issue-title">⚠️ ' + (issue.title || '') + '</div>';
            html += '<div class="issue-detail">';
            if (issue.cause) html += '<span><b>Cause:</b> ' + issue.cause + '</span>';
            if (issue.impact) html += '<span><b>Impact:</b> ' + issue.impact + '</span>';
            if (issue.fix) html += '<span class="issue-fix"><b>Fix:</b> ' + issue.fix + '</span>';
            html += '</div></li>';
        });
        html += '</ul>';
    }
    html += '</div>';
    
    // Recent errors
    if (data.recent_errors && data.recent_errors.length > 0) {
        html += '<div class="log-section"><h3>Recent Errors</h3>';
        data.recent_errors.forEach(log => {
            const time = log.timestamp ? log.timestamp.substring(11, 19) : '';
            const msg = (log.message || '').substring(0, 200);
            html += '<div class="log-entry"><span class="log-time">' + time + '</span> <span class="log-svc">[' + log.service + ']</span> ' + msg + '</div>';
        });
        html += '</div>';
    }
    
    html += '<div class="refresh-info">Last check: ' + (data.last_check || 'now') + ' · Refreshes every 30 seconds</div>';
    
    document.getElementById('content').innerHTML = html;
}

fetchStatus();
setInterval(fetchStatus, 30000);
</script>
</body>
</html>"""
