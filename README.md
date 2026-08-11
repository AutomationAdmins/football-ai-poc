# Football AI Editorial Assistant - POC

This project is a demo newsroom assistant for live football coverage.

You enter two live match events at the same time. The app decides which one matters more editorially, generates grounded stats-style insights, and shows the background data behind each event.

## What This App Does

### In simple terms

Think of this as a small producer assistant for a live football show.

- You type in two live events.
- The app checks whether those events are worth talking about.
- It looks up mock historical and league context.
- It asks an AI model which event should be shown first.
- It asks the AI model for a few stats lines for each valid event.
- It shows the event cards on the dashboard in the same order you entered them.
- It shows the editorial ranking separately, so Input 1 and Input 2 never get mixed up.

### In technical terms

The application is a FastAPI web app with server-rendered Jinja templates.

- `app.py` orchestrates request handling and ties all modules together.
- `event_processor.py` normalizes incoming event payloads and filters non-interesting event types.
- `sports_data.py` loads mock data from `historical_stats.json` and returns league, fixture, player, and team context.
- `editorial_context.py` merges live event facts with historical context into a grounded editorial context object.
- `prompt_builder.py` creates one prompt for ranking simultaneous events and another for insight generation.
- `ai_engine.py` calls the Groq-hosted OpenAI-compatible API, parses JSON responses, and grounds generated insight numbers against allowed facts.
- `templates/index.html` is the main dashboard.
- `templates/stats.html` is the separate stats and context page.

## Quick Start

### Requirements

- Python 3.12 recommended
- A valid `GROQ_API_KEY`

### Install

```bash
pip install -r requirements.txt
```

### Run locally

Windows PowerShell:

```powershell
$env:GROQ_API_KEY="your-key-here"
uvicorn app:app --reload --port 8080
```

macOS or Linux:

```bash
export GROQ_API_KEY="your-key-here"
uvicorn app:app --reload --port 8080
```

Open `http://localhost:8080`

## How The Flow Works

### User flow

1. Enter two events on the dashboard.
2. Click `Send Both Events`.
3. The backend processes each input separately.
4. Ignored events stay visible, but they do not go to the AI ranking step.
5. Valid events are ranked for editorial importance.
6. Insights are generated for each ranked event.
7. The dashboard shows:
   - the original input order
   - the rank and priority for each processed event
   - the recommended lead story
8. The stats page shows the background data used for each event.

### Internal pipeline

1. `POST /event` receives `input_1` and `input_2`.
2. `_process_input()` normalizes each event and enriches it with stats and editorial context.
3. `build_editorial_prompt()` creates a comparison prompt from all valid events.
4. `rank_events()` returns a ranked JSON response.
5. Ranking metadata is attached back onto the original event objects.
6. `build_insight_prompt()` is run for each ranked event.
7. `generate_insights()` returns grounded insight lines.
8. Results are stored in memory for the dashboard and stats page.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Basic health check |
| `GET` | `/` | Main dashboard |
| `GET` | `/stats` | Stats and context page |
| `POST` | `/event` | Submit the two live event inputs |
| `POST` | `/approve/{event_index}/{insight_index}` | Mark one insight as approved |
| `POST` | `/reject/{event_index}/{insight_index}` | Mark one insight as rejected |

## Example `POST /event` Payload

```json
{
  "input_1": {
    "event": "GOAL",
    "league": "Premier League",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "opponent": "Chelsea",
    "minutes": 87,
    "score": "2-1"
  },
  "input_2": {
    "event": "GOAL",
    "league": "EFL Championship",
    "player": "Crysencio Summerville",
    "team": "Leeds United",
    "opponent": "Sunderland",
    "minutes": 87,
    "score": "1-1"
  }
}
```

## Interesting Event Types

These event types are treated as editorially interesting and can trigger ranking and insight generation:

- `GOAL`
- `PENALTY`
- `RED_CARD`
- `HALF_TIME`
- `FULL_TIME`
- `OWN_GOAL`
- `VAR_DECISION`

All other event types are ignored and shown as ignored in the UI.

## File Guide

### Main application files

`app.py`

- Layman version: this is the traffic controller of the app. It receives the two event inputs, sends them through the pipeline, and decides what gets shown on the pages.
- Technical version: defines the FastAPI app, request models, route handlers, in-memory result storage, ranking flow, and insight generation flow.

`ai_engine.py`

- Layman version: this is the part that talks to the AI.
- Technical version: initializes the Groq OpenAI-compatible client, sends prompts, strips markdown wrappers from model output, parses JSON, and grounds insight numbers against allowed facts.

`event_processor.py`

- Layman version: this checks whether an event is important enough to care about and tidies the event fields.
- Technical version: validates the incoming event type against `INTERESTING_EVENTS` and maps the payload into the normalized event structure used by the rest of the app.

`sports_data.py`

- Layman version: this is the mock football memory bank.
- Technical version: loads `historical_stats.json`, matches league and fixture context, selects relevant player and team data, and applies small stat increments to reflect the event that just happened.

`editorial_context.py`

- Layman version: this builds the full story around an event.
- Technical version: merges normalized event data with fixture, team, player, and league context, then derives editorial facts and live match state used in prompts.

`prompt_builder.py`

- Layman version: this writes the instructions that the AI sees.
- Technical version: builds deterministic ranking and insight prompts from cleaned context objects and removes `None` fields so the model only receives relevant facts.

`historical_stats.json`

- Layman version: this is the fake data file that powers the demo.
- Technical version: contains mocked league, fixture, player, team, and weighting data used by `sports_data.py`.

### UI files

`templates/index.html`

- Layman version: this is the main page where you enter events and review the AI output.
- Technical version: server-rendered Jinja template for the dashboard, including the two-input form, live event cards, ranking display, and insight approval workflow.

`templates/stats.html`

- Layman version: this is the page where you inspect the background stats behind each event.
- Technical version: server-rendered Jinja template that displays the stored event summary, ranking metadata, lead story summary, and expanded stats context.

`static/`

- Layman version: this folder is where shared frontend assets would live if needed.
- Technical version: reserved for static files such as CSS, images, or JavaScript, though the current templates mainly use inline styling.

### Deployment and dependency files

`requirements.txt`

- Layman version: this lists the Python packages the app needs.
- Technical version: pinned Python dependencies for FastAPI, Uvicorn, OpenAI client support, Jinja2, and multipart form handling.

`Dockerfile`

- Layman version: this is the container recipe for running the app anywhere consistently.
- Technical version: builds a Python 3.12 slim container, installs dependencies, copies the repo, exposes port `8080`, and runs Uvicorn.

## Notes For Demo Use

- This is a dummy POC backed by mock data.
- Rankings and insights depend on the facts supplied in the mock dataset.
- Input cards keep their original identity even if the editorial ranking chooses a different lead story.
- The app stores only the latest submitted result set in memory.

## Deploy To Cloud Run

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/football-ai-poc

gcloud run deploy football-ai-poc \
  --image gcr.io/YOUR_PROJECT/football-ai-poc \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars GROQ_API_KEY=your-key-here
```

- checking