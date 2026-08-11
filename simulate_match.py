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

_ARSENAL_CHELSEA = [
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
        "build_up_players": ["Martin Ødegaard", "Declan Rice"],
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
        "build_up_players": ["Enzo Fernández", "Raheem Sterling"],
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
        "build_up_players": ["Ben White"],
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
        "xG": 0.85,
        "pass_accuracy": 88.5,
        "pressure_index": 20,
        "build_up_players": ["Leandro Trossard", "Kai Havertz"],
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

_LEEDS_SUNDERLAND = [
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
        "build_up_players": ["Ilia Gruev", "Willy Gnonto"],
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
        "build_up_players": ["Jobe Bellingham", "Dan Ballard"],
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
        "build_up_players": ["Crysencio Summerville", "Ethan Ampadu"],
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
        "build_up_players": ["Georginio Rutter", "Pascal Struijk"],
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
        "build_up_players": ["Adil Aouchiche", "Abdoullah Ba"],
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
        "build_up_players": ["Willy Gnonto", "Joe Rodon"],
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

# Haaland needs 2 goals for 100 PL milestone — he scores a hat-trick here
_MANCITY_MANUTD = [
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 12,
        "score": "1-0",
        "x": 94.0,
        "y": 50.0,
        "xG": 0.09,
        "pass_accuracy": 88.2,
        "pressure_index": 55,
        "build_up_players": ["Kevin De Bruyne", "Phil Foden"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Marcus Rashford",
        "team": "Manchester United",
        "opponent": "Manchester City",
        "minutes": 34,
        "score": "1-1",
        "x": 86.5,
        "y": 35.0,
        "xG": 0.31,
        "pass_accuracy": 72.4,
        "pressure_index": 78,
        "build_up_players": ["Bruno Fernandes", "Rasmus Hojlund"],
    },
    {
        "event": "HALF_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 45,
        "score": "1-1",
        "pass_accuracy": 81.0,
        "pressure_index": 60,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 58,
        "score": "2-1",
        "x": 89.0,
        "y": 52.0,
        "xG": 0.62,
        "pass_accuracy": 84.5,
        "pressure_index": 42,
        "build_up_players": ["Bernardo Silva", "Phil Foden"],
    },
    {
        "event": "RED_CARD",
        "league": "Premier League",
        "player": "Bruno Fernandes",
        "team": "Manchester United",
        "opponent": "Manchester City",
        "minutes": 68,
        "score": "2-1",
        "x": 40.0,
        "y": 55.0,
        "pressure_index": 91,
        "pass_accuracy": 68.3,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Phil Foden",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 77,
        "score": "3-1",
        "x": 82.0,
        "y": 44.0,
        "xG": 0.41,
        "pass_accuracy": 87.1,
        "pressure_index": 30,
        "build_up_players": ["Kevin De Bruyne", "Erling Haaland"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Erling Haaland",
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 86,
        "score": "4-1",
        "x": 96.0,
        "y": 50.0,
        "xG": 0.78,
        "pass_accuracy": 89.0,
        "pressure_index": 18,
        "build_up_players": ["Phil Foden", "Jack Grealish"],
    },
    {
        "event": "FULL_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Manchester City",
        "opponent": "Manchester United",
        "minutes": 90,
        "score": "4-1",
        "pass_accuracy": 85.3,
        "pressure_index": 38,
    },
]

# Spurs chase top 4; Palace fight relegation — late Richarlison winner
_PALACE_SPURS = [
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Jean-Philippe Mateta",
        "team": "Crystal Palace",
        "opponent": "Tottenham Hotspur",
        "minutes": 19,
        "score": "1-0",
        "x": 88.0,
        "y": 48.0,
        "xG": 0.38,
        "pass_accuracy": 70.5,
        "pressure_index": 74,
        "build_up_players": ["Eberechi Eze", "Michael Olise"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Son Heung-min",
        "team": "Tottenham Hotspur",
        "opponent": "Crystal Palace",
        "minutes": 33,
        "score": "1-1",
        "x": 91.0,
        "y": 42.0,
        "xG": 0.52,
        "pass_accuracy": 79.8,
        "pressure_index": 65,
        "build_up_players": ["Dejan Kulusevski", "James Maddison"],
    },
    {
        "event": "HALF_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Crystal Palace",
        "opponent": "Tottenham Hotspur",
        "minutes": 45,
        "score": "1-1",
        "pass_accuracy": 75.2,
        "pressure_index": 70,
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Eberechi Eze",
        "team": "Crystal Palace",
        "opponent": "Tottenham Hotspur",
        "minutes": 58,
        "score": "2-1",
        "x": 79.0,
        "y": 36.0,
        "xG": 0.14,
        "pass_accuracy": 72.0,
        "pressure_index": 80,
        "build_up_players": ["Jean-Philippe Mateta", "Tyrick Mitchell"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Dejan Kulusevski",
        "team": "Tottenham Hotspur",
        "opponent": "Crystal Palace",
        "minutes": 71,
        "score": "2-2",
        "x": 84.0,
        "y": 58.0,
        "xG": 0.29,
        "pass_accuracy": 82.4,
        "pressure_index": 58,
        "build_up_players": ["Son Heung-min", "Richarlison"],
    },
    {
        "event": "GOAL",
        "league": "Premier League",
        "player": "Richarlison",
        "team": "Tottenham Hotspur",
        "opponent": "Crystal Palace",
        "minutes": 89,
        "score": "3-2",
        "x": 93.0,
        "y": 50.0,
        "xG": 0.67,
        "pass_accuracy": 80.1,
        "pressure_index": 22,
        "build_up_players": ["Son Heung-min", "Pedro Porro"],
    },
    {
        "event": "FULL_TIME",
        "league": "Premier League",
        "player": None,
        "team": "Crystal Palace",
        "opponent": "Tottenham Hotspur",
        "minutes": 90,
        "score": "3-2",
        "pass_accuracy": 76.8,
        "pressure_index": 50,
    },
]

# Man City vs Man Utd 2026-27 — tests new GCS CSV historical data pipeline
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
    "arsenal-chelsea":  _ARSENAL_CHELSEA,
    "leeds-sunderland": _LEEDS_SUNDERLAND,
    "mancity-manutd":   _MANCITY_MANUTD,
    "palace-spurs":     _PALACE_SPURS,
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
