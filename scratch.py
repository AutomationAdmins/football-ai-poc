import json
from ai_engine import generate_insights, flatten_for_grounding
from prompt_builder import build_insight_prompt
from editorial_context import build_editorial_context

event = {
    "status": "interesting",
    "event_type": "GOAL",
    "league": "Premier League",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "opponent": "Chelsea",
    "minute": 14,
    "score": "1-0"
}
stats_context = json.load(open("historical_stats.json"))
editorial_ctx = build_editorial_context(event, stats_context)
editorial_ctx["match_state"] = {}
editorial_ctx["player_performance"] = None
editorial_ctx["used_insights"] = []

prompt = build_insight_prompt(editorial_ctx)
allowed_facts = flatten_for_grounding(editorial_ctx)

try:
    res = generate_insights(prompt, allowed_facts)
    print("SUCCESS")
    print(json.dumps(res, indent=2))
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
