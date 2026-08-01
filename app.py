from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ai_engine import (
    generate_insights,
    rank_events,
)

from event_processor import process_event

from sports_data import get_context

from editorial_context import build_editorial_context

from prompt_builder import (
    build_editorial_prompt,
    build_insight_prompt,
)

app = FastAPI(title="Football AI Editorial Assistant")

#app.mount("/static", StaticFiles(directory="static"), name="static")
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


def _process_input(payload: EventInputPayload, original_input_index: int) -> dict:

    processed = process_event(payload.model_dump())

    if processed["status"] == "ignored":
        return {
            "status": "ignored",
            "original_input_index": original_input_index,
            "event": processed,
            "reason": processed["reason"],
        }

    stats_context = get_context(processed)

    editorial_context = build_editorial_context(
        processed,
        stats_context,
    )

    return {
        "status": "processed",
        "original_input_index": original_input_index,
        "event": processed,
        "stats": stats_context,
        "editorial_context": editorial_context,
    }

@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "result": _last_result})


@app.get("/stats", response_class=HTMLResponse)
def stats_dashboard(request: Request):
    return templates.TemplateResponse("stats.html", {"request": request, "result": _last_result})


@app.post("/event")
def handle_event(payload: EventBatchPayload):

    global _last_result

    results = [
        _process_input(payload.input_1, 0),
        _process_input(payload.input_2, 1),
    ]

    valid_events = [
        r for r in results
        if r["status"] == "processed"
    ]

    #
    # Nothing to compare
    #

    if not valid_events:

        _last_result = {
            "results": results,
            "ranked_results": [],
            "lead_story": None,
        }

        return {
            "status": "processed",
            "results": results,
            "ranked_results": [],
            "lead_story": None,
        }

    #
    # Editorial Ranking
    #

    ranking_prompt = build_editorial_prompt(
        [
            e["editorial_context"]
            for e in valid_events
        ]
    )

    ranking = rank_events(ranking_prompt)

    print("\n========== AI RANKING ==========")
    print(ranking)
    print("===============================\n")

    for rank_order, item in enumerate(ranking["ranking"], start=1):

        idx = item["event_index"]

        valid_events[idx]["priority"] = item["priority"]

        valid_events[idx]["editorial_reason"] = item["reason"]

        valid_events[idx]["rank_order"] = rank_order

    #
    # Highest first
    #

    ranked_results = sorted(
        valid_events,
        key=lambda x: (
            {
                "Critical": 4,
                "High": 3,
                "Medium": 2,
                "Low": 1,
            }.get(
                x.get("priority"),
                0,
            )
        ),
        reverse=True,
    )

    #
    # Generate Insights
    #

    for event in ranked_results:

        prompt = build_insight_prompt(
            event["editorial_context"]
        )

        allowed = event["editorial_context"]["editorial_facts"]

        insights = generate_insights(
            prompt,
            allowed,
        )

        event["insights"] = [
            {
                "text": x,
                "decision": None,
            }
            for x in insights
        ]

    _last_result = {
        "results": results,
        "ranked_results": ranked_results,
        "lead_story": ranked_results[0] if ranked_results else None,
    }

    return {
        "status": "processed",
        "results": results,
        "ranked_results": ranked_results,
        "lead_story": ranked_results[0] if ranked_results else None,
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
