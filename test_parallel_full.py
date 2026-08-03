import concurrent.futures
from ai_engine import _chat, generate_insights, flatten_for_grounding
from sports_data import get_context
from editorial_context import build_editorial_context
from prompt_builder import build_insight_prompt

event1 = {
    "event": "GOAL",
    "league": "Premier League",
    "player": "Bukayo Saka",
    "team": "Arsenal",
    "opponent": "Chelsea",
    "minutes": 87,
    "score": "2-1"
}

event2 = {
    "event": "GOAL",
    "league": "EFL Championship",
    "player": "Crysencio Summerville",
    "team": "Leeds United",
    "opponent": "Sunderland",
    "minutes": 87,
    "score": "1-1"
}

from event_processor import process_event

def run_insight(e):
    processed = process_event(e)
    stats = get_context(processed)
    edit = build_editorial_context(processed, stats)
    prompt = build_insight_prompt(edit)
    allowed = flatten_for_grounding(edit)
    print(f"Calling generate_insights for {e['player']}")
    res = generate_insights(prompt, allowed)
    print(f"Success for {e['player']}")
    return res

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    futures = [executor.submit(run_insight, e) for e in [event1, event2]]
    for f in concurrent.futures.as_completed(futures):
        try:
            print("Finished:", f.result()['lead_story'])
        except Exception as ex:
            print("Error:", ex)
