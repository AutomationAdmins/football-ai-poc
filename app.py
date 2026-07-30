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

# In-memory store of the most recent processed event for the dashboard
_last_result: dict = {}


class EventPayload(BaseModel):
    event: str
    player: str | None = None
    team: str | None = None
    minute: int | None = None
    score: str | None = None


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "result": _last_result})


@app.post("/event")
def handle_event(payload: EventPayload):
    global _last_result

    processed = process_event(payload.model_dump())

    if processed["status"] == "ignored":
        _last_result = {"status": "ignored", "event": payload.model_dump()}
        return {"status": "ignored", "reason": processed["reason"]}

    stats_context = get_context(processed)
    prompt = build_prompt(processed, stats_context)
    insights = generate_insights(prompt)

    _last_result = {
        "status": "processed",
        "event": processed,
        "stats": stats_context,
        "insights": [{"text": insight, "decision": None} for insight in insights],
    }

    return {"status": "processed", "insights": insights}


@app.post("/approve/{index}")
def approve_insight(index: int):
    if not _last_result or index >= len(_last_result.get("insights", [])):
        return {"error": "Invalid index"}
    _last_result["insights"][index]["decision"] = "approved"
    return {"status": "approved", "index": index}


@app.post("/reject/{index}")
def reject_insight(index: int):
    if not _last_result or index >= len(_last_result.get("insights", [])):
        return {"error": "Invalid index"}
    _last_result["insights"][index]["decision"] = "rejected"
    return {"status": "rejected", "index": index}
