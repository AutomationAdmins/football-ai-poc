import json
import os

_STATS_PATH = os.path.join(os.path.dirname(__file__), "historical_stats.json")


def _load_stats() -> dict:
    with open(_STATS_PATH, "r") as f:
        return json.load(f)


def get_context(event: dict) -> dict:
    stats = _load_stats()
    context = {}

    player = event.get("player")
    if player and player in stats.get("players", {}):
        context["player_stats"] = {player: stats["players"][player]}

    team = event.get("team")
    if team and team in stats.get("teams", {}):
        context["team_stats"] = {team: stats["teams"][team]}

    return context
