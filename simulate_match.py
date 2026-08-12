"""
Unified match simulation script — publishes fake Opta events to Pub/Sub.
Run this to drive the pipeline end-to-end without a real Opta feed.

Usage:
    python simulate_match.py --match arsenal-chelsea
    python simulate_match.py --match leeds-sunderland
    python simulate_match.py --match mancity-manutd
    python simulate_match.py --match palace-spurs
    python simulate_match.py --match arsenal-chelsea --fixture-id my-custom-id --delay 2

Available match keys:
    arsenal-chelsea     Arsenal vs Chelsea (Premier League, title race)
    leeds-sunderland    Leeds United vs Sunderland (Championship, promotion)
    mancity-manutd      Manchester City vs Manchester United (Man Derby, Haaland milestone)
    palace-spurs        Crystal Palace vs Tottenham (relegation vs Champions League)
"""

import argparse
import base64
import json
import subprocess
import time
import urllib.request

_PROJECT = "avid-invention-484506-g9"
_TOPIC = "opta-live-events"

# Default fixture IDs per match key — override with --fixture-id
_DEFAULT_FIXTURE_IDS: dict[str, str] = {
    "arsenal-chelsea":   "arsenal-vs-chelsea-2025-08-02",
    "leeds-sunderland":  "leeds-vs-sunderland-2025-08-02",
    "mancity-manutd":    "man-city-vs-man-utd-2025-03-15",
    "palace-spurs":      "crystal-palace-vs-tottenham-2025-03-15",
    "mancity-manutd-2627": "man-city-vs-man-utd-2026-09-13",
}

# ---------------------------------------------------------------------------
# Match event registry
# ---------------------------------------------------------------------------

_MANCITY_MANUTD_2627 = [
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 8,
        "score": "1-0",
        "date": "2026-09-13",
        "x": 93.0,
        "y": 48.5,
        "xG": 0.15,
        "pass_accuracy": 87.3,
        "pressure_index": 52,
        "build_up_players": ["Kevin De Bruyne", "Phil Foden"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Marcus Rashford",
        "team": "Manchester United",
        "opponent": "Manchester City",
        "minutes": 27,
        "score": "1-1",
        "date": "2026-09-13",
        "x": 85.0,
        "y": 38.0,
        "xG": 0.28,
        "pass_accuracy": 74.5,
        "pressure_index": 71,
        "build_up_players": ["Bruno Fernandes", "Alejandro Garnacho"],
    },
    {
        "event": "HALF_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 45,
        "score": "1-1",
        "date": "2026-09-13",
        "pass_accuracy": 82.0,
        "pressure_index": 60,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 55,
        "score": "2-1",
        "date": "2026-09-13",
        "x": 91.0,
        "y": 50.0,
        "xG": 0.72,
        "pass_accuracy": 85.8,
        "pressure_index": 40,
        "build_up_players": ["Bernardo Silva", "Kevin De Bruyne"],
    },
    {
        "event": "RED_CARD",
        "league": "Premier League",
        "player": "Bruno Fernandes",
        "team": "Manchester United",
        "opponent": "Manchester City",
        "minutes": 64,
        "score": "2-1",
        "date": "2026-09-13",
        "x": 42.0,
        "y": 55.0,
        "pressure_index": 89,
        "pass_accuracy": 69.0,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 78,
        "score": "3-1",
        "date": "2026-09-13",
        "x": 95.0,
        "y": 50.0,
        "xG": 0.82,
        "pass_accuracy": 88.5,
        "pressure_index": 22,
        "build_up_players": ["Phil Foden", "Jack Grealish"],
    },
    {
        "event": "FULL_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 90,
        "score": "3-1",
        "date": "2026-09-13",
        "pass_accuracy": 86.1,
        "pressure_index": 35,
    },
]

MATCH_REGISTRY: dict[str, list[dict]] = {
    "mancity-manutd-2627": _MANCITY_MANUTD_2627,
}


def publish_event_pubsub(fixture_id: str, event: dict) -> None:
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


def publish_event_local(fixture_id: str, event: dict, backend_url: str) -> None:
    payload = {**event, "fixture_id": fixture_id}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    envelope = {"message": {"data": encoded}}
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(
        f"{backend_url}/pubsub/push",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode())
    print(f"  Sent [{event['event']}] at {event.get('minutes', '?')}' — {result.get('status', 'ok')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a match by publishing events to Pub/Sub or local backend")
    parser.add_argument(
        "--match",
        choices=list(MATCH_REGISTRY.keys()),
        required=True,
        help="Match to simulate",
    )
    parser.add_argument(
        "--fixture-id",
        default=None,
        help="Override the Firestore/GCS fixture ID (default derived from --match)",
    )
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between events")
    parser.add_argument(
        "--local",
        metavar="URL",
        nargs="?",
        const="http://127.0.0.1:8000",
        default=None,
        help="Send events directly to local backend instead of Pub/Sub (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    fixture_id = args.fixture_id or _DEFAULT_FIXTURE_IDS[args.match]
    events = MATCH_REGISTRY[args.match]

    if args.local:
        print(f"Simulating: {args.match}  →  fixture_id={fixture_id}")
        print(f"Sending {len(events)} events directly to {args.local}\n")
        for i, event in enumerate(events, start=1):
            print(f"[{i}/{len(events)}] ", end="", flush=True)
            publish_event_local(fixture_id, event, args.local)
            if i < len(events):
                time.sleep(args.delay)
    else:
        print(f"Simulating: {args.match}  →  fixture_id={fixture_id}")
        print(f"Publishing {len(events)} events to projects/{_PROJECT}/topics/{_TOPIC}\n")
        for i, event in enumerate(events, start=1):
            print(f"[{i}/{len(events)}] ", end="", flush=True)
            publish_event_pubsub(fixture_id, event)
            if i < len(events):
                time.sleep(args.delay)

    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
