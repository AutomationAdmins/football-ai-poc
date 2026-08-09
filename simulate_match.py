"""
Match simulation script — publishes fake Opta events to the Pub/Sub topic.
Run this to drive the pipeline end-to-end without a real Opta feed.

Usage:
    python simulate_match.py --fixture-id arsenal-vs-chelsea-2025-08-02

Each event is published with a 3-second gap so you can watch insights appear
in Firestore / the dashboard in real time.
"""

import argparse
import json
import subprocess
import time

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
        "x": 88.5,
        "y": 40.2,
        "xG": 0.12,
        "pass_accuracy": 85.4,
        "pressure_index": 62,
        "build_up_players": ["Martin Ødegaard", "Declan Rice"]
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Cole Palmer",
        "team": "Chelsea",
        "opponent": "Arsenal",
        "minutes": 31,
        "score": "1-1",
        "x": 92.1,
        "y": 50.0,
        "xG": 0.45,
        "pass_accuracy": 78.1,
        "pressure_index": 75,
        "build_up_players": ["Enzo Fernández", "Raheem Sterling"]
    },
    {
        "event": "VAR_DECISION",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 38,
        "score": "1-1",
        "pass_accuracy": 81.2,
        "pressure_index": 68,
    },
    {
        "event": "HALF_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 45,
        "score": "1-1",
        "pass_accuracy": 82.5,
        "pressure_index": 65,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Bukayo Saka",
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 67,
        "score": "2-1",
        "x": 75.3,
        "y": 30.1,
        "xG": 0.05,
        "pass_accuracy": 82.0,
        "pressure_index": 45,
        "build_up_players": ["Ben White"]
    },
    {
        "event": "RED_CARD",
        "league": "Premier League",
        "player": "Reece James",
        "team": "Chelsea",
        "opponent": "Arsenal",
        "minutes": 78,
        "score": "2-1",
        "x": 45.0,
        "y": 60.5,
        "pressure_index": 88,
        "pass_accuracy": 73.5,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Bukayo Saka",
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 89,
        "score": "3-1",
        "x": 95.0,
        "y": 50.0,
        "xG": 0.85, # penalty or tap-in like xG
        "pass_accuracy": 88.5,
        "pressure_index": 20,
        "build_up_players": ["Leandro Trossard", "Kai Havertz"]
    },
    {
        "event": "FULL_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Arsenal",
        "opponent": "Chelsea",
        "minutes": 90,
        "score": "3-1",
        "pass_accuracy": 84.2,
        "pressure_index": 55,
    },
]


def publish_event(fixture_id: str, event: dict) -> None:
    payload = {**event, "fixture_id": fixture_id}
    message = json.dumps(payload, separators=(",", ":"))
    result = subprocess.run(
        [
            "gcloud",
            "pubsub",
            "topics",
            "publish",
            _TOPIC,
            "--message",
            message,
            "--project",
            _PROJECT,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip() or result.stderr.strip()
    print(f"  Published [{event['event']}] at {event.get('minutes', '?')}' — {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a match by publishing events to Pub/Sub")
    parser.add_argument("--fixture-id", default="arsenal-vs-chelsea-2025-08-02")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between events")
    args = parser.parse_args()

    print(f"Simulating match: {args.fixture_id}")
    print(f"Publishing {len(MATCH_EVENTS)} events to projects/{_PROJECT}/topics/{_TOPIC}\n")

    for i, event in enumerate(MATCH_EVENTS, start=1):
        print(f"[{i}/{len(MATCH_EVENTS)}] ", end="")
        publish_event(args.fixture_id, event)
        if i < len(MATCH_EVENTS):
            time.sleep(args.delay)

    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
