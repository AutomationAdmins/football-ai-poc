import json
from ai_engine import rank_events, generate_insights, flatten_for_grounding
from prompt_builder import build_insight_prompt
import traceback

context = {
    "event": {
        "event_type": "GOAL",
        "player": "Virgil van Dijk",
        "team": "Liverpool",
        "opponent": "Manchester United",
        "score": "1-1",
        "minute": "87"
    },
    "player": {
        "season_goals": 2,
        "season_assists": 1
    },
    "commentator_facts": {
        "what_happened": "87' GOAL — 1-1 (Liverpool vs Manchester United)",
        "goal_type": "equaliser",
        "minute": "87",
        "score": "1-1",
        "player": "Virgil van Dijk",
        "team": "Liverpool",
        "opponent": "Manchester United"
    }
}
try:
    prompt = build_insight_prompt(context)
    allowed = flatten_for_grounding(context)
    print("calling generate_insights...")
    result = generate_insights(prompt, allowed)
    print("SUCCESS")
    print(result)
except Exception as e:
    print("ERROR")
    traceback.print_exc()

