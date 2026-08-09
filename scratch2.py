import json
from ai_engine import _chat, _strip_json, _is_grounded, _allowed_numbers, _extract_numbers
from ai_engine import flatten_for_grounding
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

raw = _chat(prompt, max_tokens=1200)
raw = _strip_json(raw)
start = raw.find("{")
end = raw.rfind("}") + 1
data = json.loads(raw[start:end])
lead_story = str(data.get("lead_story", "")).strip()

print(f"Lead story: {lead_story}")
allowed = _allowed_numbers(allowed_facts)
extracted = _extract_numbers(lead_story)
print(f"Extracted numbers: {extracted}")
print(f"Allowed numbers: {allowed}")
print(f"Diff: {extracted - allowed}")
