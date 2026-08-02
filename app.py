import base64
import json
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ai_engine import flatten_for_grounding, generate_insights, rank_events
from event_processor import process_event
from sports_data import get_context
from editorial_context import build_editorial_context
from prompt_builder import build_editorial_prompt, build_insight_prompt
from firestore_client import (
    append_match_event,
    get_match_history,
    write_insight,
    get_all_pending_insights,
    record_decision,
    get_used_insight_lines,
)
from match_state_tracker import (
    build_match_state,
    detect_player_performance,
    filter_duplicate_insights,
    format_match_state_for_prompt,
)

_FIXTURE_ID = os.environ.get("FIXTURE_ID", "arsenal-vs-chelsea-2025-08-02")

app = FastAPI(title="Football AI Editorial Assistant")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------------------------------------------------------------------------
# Pub/Sub push endpoint — Opta events arrive here from the topic
# ---------------------------------------------------------------------------

from fastapi import BackgroundTasks

def generate_and_save_insight(fixture_id, processed, prompt, allowed_facts, editorial_ctx):
    try:
        insight_result = generate_insights(prompt, allowed_facts, editorial_ctx)
        
        # Filter out duplicate insights
        used_lines = editorial_ctx.get("used_insights", [])
        filtered_insights = filter_duplicate_insights(
            insight_result["insights"],
            set(used_lines)
        )
        
        # Only write if we have novel insights
        if filtered_insights:
            write_insight(fixture_id, {
                "lead_story": insight_result["lead_story"],
                "insights": filtered_insights,
                "event_type": processed.get("event_type"),
                "player": processed.get("player"),
                "team": processed.get("team"),
                "minute": processed.get("minute"),
                "score": processed.get("score"),
            })
        else:
            print(f"All insights for {fixture_id} were duplicates - skipped writing")
    except Exception as e:
        print(f"Error generating insight in background: {e}")

@app.post("/pubsub/push")
async def pubsub_push(request: Request, background_tasks: BackgroundTasks):
    envelope = await request.json()
    message = envelope.get("message", {})
    raw_data = message.get("data", "")

    try:
        event_data = json.loads(base64.b64decode(raw_data).decode("utf-8"))
    except Exception:
        # Bad message — ack it so Pub/Sub doesn't retry garbage
        return JSONResponse(status_code=200, content={"status": "malformed_message_acked"})

    fixture_id = event_data.pop("fixture_id", _FIXTURE_ID)
    processed = process_event(event_data)

    if processed["status"] == "ignored":
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": processed["reason"]})

    # Layer 3 — pre-match stats from GCS (via sports_data which calls gcs_client)
    stats_context = get_context(processed)

    # Layer 2 — current match history from Firestore
    match_history = get_match_history(fixture_id)

    # Layer 1 — live match state (goals today, hat-tricks, etc.)
    match_state = build_match_state(match_history, processed)

    # Get previously shown insights for anti-repetition
    used_insight_lines = get_used_insight_lines(fixture_id)

    # Detect player performance milestones
    player_performance = None
    if processed.get("player"):
        player_performance = detect_player_performance(
            processed["player"], match_state, processed
        )

    # Build editorial context and prompt
    editorial_ctx = build_editorial_context(processed, stats_context)
    editorial_ctx["match_state"] = match_state
    editorial_ctx["player_performance"] = player_performance
    editorial_ctx["used_insights"] = list(used_insight_lines)[:20]  # Limit to prevent prompt bloat

    prompt = build_insight_prompt(editorial_ctx, match_history=match_history)
    allowed_facts = flatten_for_grounding(editorial_ctx)

    # Persist event to match log BEFORE background task (so next events see it)
    append_match_event(fixture_id, processed)

    # Persist AI insight asynchronously to avoid blocking the webhook
    background_tasks.add_task(generate_and_save_insight, fixture_id, processed, prompt, allowed_facts, editorial_ctx)

    return JSONResponse(status_code=200, content={"status": "processing_in_background"})


# ---------------------------------------------------------------------------
# Dashboard — reads live insights from Firestore
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    insights = get_all_pending_insights()
    return templates.TemplateResponse("index.html", {"request": request, "insights": insights})


@app.get("/api/insights")
def api_insights():
    """JSON endpoint for the Next.js frontend to poll."""
    return get_all_pending_insights()


# ---------------------------------------------------------------------------
# Statistician decisions — approve / reject
# ---------------------------------------------------------------------------

@app.post("/decide/{fixture_id}/{insight_id}")
def decide(fixture_id: str, insight_id: str, request: Request):
    return JSONResponse(status_code=200, content={"status": "use_approve_or_reject"})


@app.post("/approve/{fixture_id}/{insight_id}")
def approve(fixture_id: str, insight_id: str):
    record_decision(fixture_id, insight_id, approved=True)
    return {"status": "approved", "fixture_id": fixture_id, "insight_id": insight_id}


@app.post("/reject/{fixture_id}/{insight_id}")
def reject(fixture_id: str, insight_id: str):
    record_decision(fixture_id, insight_id, approved=False)
    return {"status": "rejected", "fixture_id": fixture_id, "insight_id": insight_id}
