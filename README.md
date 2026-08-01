# Football AI Editorial Assistant — POC

## Quick Start (Local)

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn app:app --reload --port 8080
```

Open http://localhost:8080

## Deploy to Cloud Run

```bash
# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT/football-ai-poc

# Deploy
gcloud run deploy football-ai-poc \
  --image gcr.io/YOUR_PROJECT/football-ai-poc \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars OPENAI_API_KEY=sk-...
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | Statistician dashboard |
| POST | `/event` | Submit a live football event |
| POST | `/approve/{index}` | Approve an insight |
| POST | `/reject/{index}` | Reject an insight |

### Example POST /event

```json
{
  "event": "GOAL",
  "player": "Josh Windass",
  "team": "Wrexham",
  "minute": 87,
  "score": "2-1"
}
```

## Interesting Events (trigger AI)
GOAL, PENALTY, RED_CARD, OWN_GOAL, VAR_DECISION, HALF_TIME, FULL_TIME

All other event types are ignored and do not call the AI.
#END