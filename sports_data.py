import copy
import json
import os

_STATS_PATH = os.path.join(os.path.dirname(__file__), "historical_stats.json")

# Maps event type to which player/team counters to increment by 1
_PLAYER_INCREMENTS = {
    "GOAL":      ["season_goals", "appearances"],
    "OWN_GOAL":  ["own_goals", "appearances"],
    "RED_CARD":  ["red_cards", "appearances"],
    "PENALTY":   ["appearances"],
}

_TEAM_INCREMENTS = {
    "GOAL":      ["goals_scored_this_season"],
    "OWN_GOAL":  ["goals_conceded_this_season"],
}


def _load_stats() -> dict:
    with open(_STATS_PATH, "r") as f:
        return json.load(f)


def _matches_league(entity: dict, league: str | None) -> bool:
    return not league or entity.get("league") == league


def _find_fixture(stats: dict, league: str | None, team: str | None, opponent: str | None) -> str | None:
    if not team or not opponent:
        return None

    for fixture_name, fixture in stats.get("fixtures", {}).items():
        if league and fixture.get("competition") != league:
            continue

        teams = {fixture.get("home_team"), fixture.get("away_team")}
        if {team, opponent} == teams:
            return fixture_name

    return None


def _apply_increments(context: dict, event_type: str) -> dict:
    """Returns a deep copy of context with counters incremented to reflect the current event."""
    updated = copy.deepcopy(context)

    player_fields = _PLAYER_INCREMENTS.get(event_type, [])
    for player_stats in updated.get("player_stats", {}).values():
        for field in player_fields:
            if field in player_stats:
                player_stats[field] += 1

    team_fields = _TEAM_INCREMENTS.get(event_type, [])
    for team_stats in updated.get("team_stats", {}).values():
        for field in team_fields:
            if field in team_stats:
                team_stats[field] += 1

    return updated


def get_context(event: dict) -> dict:
    stats = _load_stats()
    context = {}

    league = event.get("league")
    fixture = _find_fixture(stats, league, event.get("team"), event.get("opponent"))

    if league and league in stats.get("leagues", {}):
        context["league_stats"] = {league: stats["leagues"][league]}

    if fixture and fixture in stats.get("fixtures", {}):
        context["fixture_stats"] = {fixture: stats["fixtures"][fixture]}

    player = event.get("player")
    if player and player in stats.get("players", {}) and _matches_league(stats["players"][player], league):
        context["player_stats"] = {player: stats["players"][player]}

    team = event.get("team")
    if team and team in stats.get("teams", {}) and _matches_league(stats["teams"][team], league):
        context["team_stats"] = {team: stats["teams"][team]}

    if fixture:
        context["fixture_lookup"] = {"selected_fixture": {"name": fixture}}

    # Increment counters to reflect the event that just happened
    return _apply_increments(context, event.get("event_type", ""))
