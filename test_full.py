import json
from ai_engine import _chat, _get_client
from sports_data import get_context
from editorial_context import build_editorial_context
from prompt_builder import build_insight_prompt
import traceback
import sys

event = {
    "event_type": "GOAL",
    "league": "Premier League",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "opponent": "Chelsea",
    "minutes": 87,
    "score": "2-1"
}

stats = get_context(event)
edit = build_editorial_context(event, stats)
prompt = build_insight_prompt(edit)

print("Prompt length:", len(prompt))

try:
    print("Calling chat...")
    res = _chat(prompt, max_tokens=1200)
    print("Success")
except Exception as e:
    print("Exception!")
    traceback.print_exc()

