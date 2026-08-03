import json
from prompt_builder import build_insight_prompt

def test_event(event_type):
    context = {
        "event": {
            "event_type": event_type,
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
            "what_happened": f"87' {event_type} — 1-1 (Liverpool vs Manchester United)",
            "goal_type": "equaliser",
            "minute": "87",
            "score": "1-1",
            "player": "Virgil van Dijk",
            "team": "Liverpool",
            "opponent": "Manchester United"
        }
    }
    
    prompt = build_insight_prompt(context)
    print(f"--- TEST: {event_type} ---")
    print(prompt[:1200]) # Print first part to see LEAD STORY
    print("\n\n")

test_event("GOAL")
test_event("PENALTY")
test_event("RED_CARD")
