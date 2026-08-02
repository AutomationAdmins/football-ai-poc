import sports_data
import event_processor

inputs = [
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Liverpool",
        "minutes": 87,
        "score": "1-0"
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "erling haaland",
        "team": "manchester city",
        "opponent": "liverpool",
        "minutes": 87,
        "score": "1-0"
    }
]

for idx, evt in enumerate(inputs):
    processed = event_processor.process_event(evt)
    ctx = sports_data.get_context(processed)
    print(f"\n--- TEST {idx+1} ---")
    print(f"Player Input: {evt['player']}")
    print(f"Team Input: {evt['team']}")
    print("Player Stats Returned:", "YES" if ctx.get('player_stats') else "NO")
    print("Team Stats Returned:", "YES" if ctx.get('team_stats') else "NO")
