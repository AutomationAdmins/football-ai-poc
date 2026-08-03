from ai_engine import _chat, _get_client, generate_insights, flatten_for_grounding
from sports_data import get_context
from editorial_context import build_editorial_context
from prompt_builder import build_insight_prompt
import traceback

event = {
    "event": "GOAL",
    "league": "Premier League",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "opponent": "Chelsea",
    "minutes": 87,
    "score": "2-1"
}

# The event payload in the server has {"event": "GOAL", "league":...}
# which process_event turns into {"event_type": "GOAL", ...}
from event_processor import process_event

processed = process_event(event)
stats = get_context(processed)
edit = build_editorial_context(processed, stats)
prompt = build_insight_prompt(edit)
allowed = flatten_for_grounding(edit)

try:
    print("Calling generate_insights...")
    res = generate_insights(prompt, allowed)
    print("Success")
except Exception as e:
    print("Exception in generate_insights!")
    traceback.print_exc()

