"""
Match simulation script — publishes fake Opta events to the Pub/Sub topic.
Run this to drive the pipeline end-to-end without a real Opta feed.

Usage:
    python simulate_match.py --fixture-id arsenal-vs-chelsea-2025-08-02

Each event is published with a 3-second gap so you can watch insights appear
in Firestore / the dashboard in real time.
"""

import argparse
import base64
import json
import time

from google.cloud import pubsub_v1

_PROJECT = "avid-invention-484506-g9"
_TOPIC = "opta-live-events"

MATCH_EVENTS = [
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Bukayo Saka",
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 14,
        "score": "1-0",
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Cole Palmer",
        "team": "Chelsea",
        "opponent": "Arsenal",
        "minutes": 31,
        "score": "1-1",
    },
    {
        "event": "VAR_DECISION",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 38,
        "score": "1-1",
    },
    {
        "event": "HALF_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 45,
        "score": "1-1",
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Bukayo Saka",
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 67,
        "score": "2-1",
    },
    {
        "event": "RED_CARD",
        "league": "Premier League",
        "player": "Reece James",
        "team": "Chelsea",
        "opponent": "Arsenal",
        "minutes": 78,
        "score": "2-1",
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Bukayo Saka",
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 89,
        "score": "3-1",
    },
    {
        "event": "FULL_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 90,
        "score": "3-1",
    },
]


def publish_event(publisher, topic_path: str, fixture_id: str, event: dict) -> None:
    payload = {**event, "fixture_id": fixture_id}
    data = json.dumps(payload).encode("utf-8")
    future = publisher.publish(topic_path, data)
    msg_id = future.result()
    print(f"  Published [{event['event']}] at {event.get('minutes', '?')}' — msg_id={msg_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a match by publishing events to Pub/Sub")
    parser.add_argument("--fixture-id", default="arsenal-vs-chelsea-2025-08-02")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between events")
    args = parser.parse_args()

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(_PROJECT, _TOPIC)

    print(f"Simulating match: {args.fixture_id}")
    print(f"Publishing {len(MATCH_EVENTS)} events to {topic_path}\n")

    for i, event in enumerate(MATCH_EVENTS, start=1):
        print(f"[{i}/{len(MATCH_EVENTS)}] ", end="")
        publish_event(publisher, topic_path, args.fixture_id, event)
        if i < len(MATCH_EVENTS):
            time.sleep(args.delay)

    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
