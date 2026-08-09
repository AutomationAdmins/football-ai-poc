"""
Match simulation — Leeds United vs Sunderland (EFL Championship)
Publishes fake Opta events to the Pub/Sub topic.

Usage:
    python simulate_leeds_sunderland.py --fixture-id leeds-vs-sunderland-2025-08-02
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
        "league": "EFL Championship",
        "player": "Crysencio Summerville",
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 8,
        "score": "1-0",
        "x": 90.2,
        "y": 45.0,
        "xG": 0.35,
        "pass_accuracy": 79.3,
        "pressure_index": 58,
        "build_up_players": ["Ilia Gruev", "Willy Gnonto"]
    },
    {
        "event": "GOAL",
        "league": "EFL Championship",
        "player": "Jack Clarke",
        "team": "Sunderland",
        "opponent": "Leeds United",
        "minutes": 23,
        "score": "1-1",
        "x": 85.7,
        "y": 55.3,
        "xG": 0.28,
        "pass_accuracy": 74.6,
        "pressure_index": 72,
        "build_up_players": ["Jobe Bellingham", "Dan Ballard"]
    },
    {
        "event": "GOAL",
        "league": "EFL Championship",
        "player": "Georginio Rutter",
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 37,
        "score": "2-1",
        "x": 78.4,
        "y": 38.9,
        "xG": 0.08,
        "pass_accuracy": 81.5,
        "pressure_index": 50,
        "build_up_players": ["Crysencio Summerville", "Ethan Ampadu"]
    },
    {
        "event": "HALF_TIME",
        "league": "EFL Championship",
        "player": None,
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 45,
        "score": "2-1",
        "pass_accuracy": 80.1,
        "pressure_index": 55,
    },
    {
        "event": "RED_CARD",
        "league": "EFL Championship",
        "player": "Dan Ballard",
        "team": "Sunderland",
        "opponent": "Leeds United",
        "minutes": 55,
        "score": "2-1",
        "x": 35.0,
        "y": 50.0,
        "pressure_index": 82,
        "pass_accuracy": 70.2,
    },
    {
        "event": "GOAL",
        "league": "EFL Championship",
        "player": "Crysencio Summerville",
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 63,
        "score": "3-1",
        "x": 91.5,
        "y": 48.2,
        "xG": 0.72,
        "pass_accuracy": 84.0,
        "pressure_index": 35,
        "build_up_players": ["Georginio Rutter", "Pascal Struijk"]
    },
    {
        "event": "GOAL",
        "league": "EFL Championship",
        "player": "Jack Clarke",
        "team": "Sunderland",
        "opponent": "Leeds United",
        "minutes": 78,
        "score": "3-2",
        "x": 88.0,
        "y": 42.5,
        "xG": 0.55,
        "pass_accuracy": 72.8,
        "pressure_index": 80,
        "build_up_players": ["Adil Aouchiche", "Abdoullah Ba"]
    },
    {
        "event": "GOAL",
        "league": "EFL Championship",
        "player": "Crysencio Summerville",
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 87,
        "score": "4-2",
        "x": 93.0,
        "y": 50.0,
        "xG": 0.90,
        "pass_accuracy": 86.2,
        "pressure_index": 25,
        "build_up_players": ["Willy Gnonto", "Joe Rodon"]
    },
    {
        "event": "FULL_TIME",
        "league": "EFL Championship",
        "player": None,
        "team": "Leeds United",
        "opponent": "Sunderland",
        "minutes": 90,
        "score": "4-2",
        "pass_accuracy": 82.7,
        "pressure_index": 48,
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
    parser = argparse.ArgumentParser(description="Simulate Leeds vs Sunderland")
    parser.add_argument("--fixture-id", default="leeds-vs-sunderland-2025-08-02")
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
