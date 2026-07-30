INTERESTING_EVENTS = {"GOAL", "PENALTY", "RED_CARD", "HALF_TIME", "FULL_TIME", "OWN_GOAL", "VAR_DECISION"}


def process_event(event: dict) -> dict:
    event_type = event.get("event", "").upper()

    if event_type not in INTERESTING_EVENTS:
        return {"status": "ignored", "reason": f"Event type '{event_type}' is not editorially interesting"}

    return {
        "status": "interesting",
        "event_type": event_type,
        "player": event.get("player"),
        "team": event.get("team"),
        "minute": event.get("minute"),
        "score": event.get("score"),
    }
