INTERESTING_EVENTS = {"GOAL", "PENALTY", "RED_CARD", "HALF_TIME", "FULL_TIME", "OWN_GOAL", "VAR_DECISION"}


def process_event(event: dict) -> dict:
    event_type = event.get("event", "").upper()

    if event_type not in INTERESTING_EVENTS:
        return {"status": "ignored", "reason": f"Event type '{event_type}' is not editorially interesting"}

    return {
        "status": "interesting",
        "event_type": event_type,
        "league": event.get("league"),
        "player": event.get("player"),
        "team": event.get("team"),
        "opponent": event.get("opponent"),
        "minute": event.get("minutes"),
        "score": event.get("score"),
        "xG": event.get("xG"),
        "pass_accuracy": event.get("pass_accuracy"),
        "pressure_index": event.get("pressure_index"),
        "x": event.get("x"),
        "y": event.get("y"),
        "build_up_players": event.get("build_up_players"),
    }
