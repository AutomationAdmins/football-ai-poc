from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ai_engine import generate_insights
from event_processor import process_event
from prompt_builder import build_prompt
from sports_data import get_context

app = FastAPI(title="Football AI Editorial Assistant")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# In-memory store of the most recent processed events for the dashboard
_last_result: dict = {}


class EventInputPayload(BaseModel):
    event: str
    league: str | None = None
    player: str | None = None
    team: str | None = None
    opponent: str | None = None
    minutes: int | None = None
    score: str | None = None


class EventBatchPayload(BaseModel):
    input_1: EventInputPayload
    input_2: EventInputPayload


def _process_input(payload: EventInputPayload) -> dict:
    processed = process_event(payload.model_dump())

    if processed["status"] == "ignored":
        return {"status": "ignored", "event": processed, "reason": processed["reason"]}

    stats_context = get_context(processed)
    prompt, allowed_facts = build_prompt(processed, stats_context)

    try:
        insights = generate_insights(prompt, allowed_facts)
    except Exception as exc:
        return {"status": "error", "event": processed, "reason": str(exc)}

    return {
        "status": "processed",
        "event": processed,
        "stats": stats_context,
        "insights": [{"text": insight, "decision": None} for insight in insights],
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "result": _last_result})


@app.post("/event")
def handle_event(payload: EventBatchPayload):
    global _last_result

    results = [
        _process_input(payload.input_1),
        _process_input(payload.input_2),
    ]

    _last_result = {"results": results}

    return {
        "status": "processed",
        "results": results,
    }

@app.post("/approve/{event_index}/{insight_index}")
def approve_insight(event_index: int, insight_index: int):
    results = _last_result.get("results", [])
    if event_index >= len(results):
        return {"error": "Invalid event index"}

    insights = results[event_index].get("insights", [])
    if insight_index >= len(insights):
        return {"error": "Invalid index"}
    insights[insight_index]["decision"] = "approved"
    return {"status": "approved", "event_index": event_index, "insight_index": insight_index}


@app.post("/reject/{event_index}/{insight_index}")
def reject_insight(event_index: int, insight_index: int):
    results = _last_result.get("results", [])
    if event_index >= len(results):
        return {"error": "Invalid event index"}

    insights = results[event_index].get("insights", [])
    if insight_index >= len(insights):
        return {"error": "Invalid index"}
    insights[insight_index]["decision"] = "rejected"
    return {"status": "rejected", "event_index": event_index, "insight_index": insight_index}
