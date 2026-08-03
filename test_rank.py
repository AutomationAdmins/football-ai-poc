from ai_engine import rank_events
from prompt_builder import build_editorial_prompt

events = [
    {
        "event": {"event_type": "GOAL", "player": "Saka"},
        "commentator_facts": {"what_happened": "87' GOAL"}
    },
    {
        "event": {"event_type": "RED_CARD", "player": "Van Dijk"},
        "commentator_facts": {"what_happened": "87' RED CARD"}
    }
]
prompt = build_editorial_prompt(events)
try:
    print(rank_events(prompt))
except Exception as e:
    print(f"Error: {e}")
