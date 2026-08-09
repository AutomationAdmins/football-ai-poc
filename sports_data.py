import copy
import os

from gcs_client import get_prematch_stats

_FIXTURE_ID = os.environ.get("FIXTURE_ID", "arsenal-vs-chelsea-2025-08-02")

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
    return get_prematch_stats(_FIXTURE_ID)


def _matches_league(entity: dict, league: str | None) -> bool:
    if not league:
        return True
    entity_league = entity.get("league")
    return entity_league and entity_league.lower() == league.lower()


def _find_fixture(stats: dict, league: str | None, team: str | None, opponent: str | None) -> str | None:
    if not team or not opponent:
        return None

    league_lower = league.lower() if league else None
    team_lower = team.lower()
    opponent_lower = opponent.lower()

    for fixture_name, fixture in stats.get("fixtures", {}).items():
        if league_lower and fixture.get("competition", "").lower() != league_lower:
            continue

        home_team = fixture.get("home_team", "").lower()
        away_team = fixture.get("away_team", "").lower()
        teams = {home_team, away_team}
        
        if {team_lower, opponent_lower} == teams:
            return fixture_name

    return None


def _apply_increments(context: dict, event_type: str, event: dict) -> dict:
    """Returns a deep copy of context with counters incremented to reflect the current event."""
    updated = copy.deepcopy(context)

    player_fields = _PLAYER_INCREMENTS.get(event_type, [])
    for player_stats in updated.get("player_stats", {}).values():
        for field in player_fields:
            if field not in player_stats:
                player_stats[field] = 0
            player_stats[field] += 1
        
        # Add live event data (xG, position, build-up) to player context
        if event.get("xG") is not None:
            player_stats["xG_this_event"] = event["xG"]
        if event.get("x") is not None and event.get("y") is not None:
            player_stats["shot_location"] = {"x": event["x"], "y": event["y"]}
        if event.get("build_up_players"):
            player_stats["assisted_by"] = event["build_up_players"]

    team_fields = _TEAM_INCREMENTS.get(event_type, [])
    for team_stats in updated.get("team_stats", {}).values():
        for field in team_fields:
            if field not in team_stats:
                team_stats[field] = 0
            team_stats[field] += 1
        
        # Add team-level live stats
        if event.get("pass_accuracy") is not None:
            team_stats["pass_accuracy_this_event"] = event["pass_accuracy"]
        if event.get("pressure_index") is not None:
            team_stats["pressure_index"] = event["pressure_index"]

    return updated


def _find_case_insensitive_key(data: dict, key: str | None) -> str | None:
    if not key or not data:
        return None
    key_lower = key.lower()
    for k in data.keys():
        if k.lower() == key_lower:
            return k
    return None


def get_context(event: dict) -> dict:
    stats = _load_stats()
    context = {}

    league = event.get("league")
    league_key = _find_case_insensitive_key(stats.get("leagues", {}), league)
    
    fixture = _find_fixture(stats, league, event.get("team"), event.get("opponent"))

    if league_key:
        context["league_stats"] = {league_key: stats["leagues"][league_key]}

    if fixture and fixture in stats.get("fixtures", {}):
        context["fixture_stats"] = {fixture: stats["fixtures"][fixture]}

    player = event.get("player")
    player_key = _find_case_insensitive_key(stats.get("players", {}), player)
    if player_key and _matches_league(stats["players"][player_key], league):
        context["player_stats"] = {player_key: stats["players"][player_key]}

    team = event.get("team")
    team_key = _find_case_insensitive_key(stats.get("teams", {}), team)
    if team_key and _matches_league(stats["teams"][team_key], league):
        context["team_stats"] = {team_key: stats["teams"][team_key]}

    if fixture:
        context["fixture_lookup"] = {"selected_fixture": {"name": fixture}}

    # Increment counters to reflect the event that just happened
    return _apply_increments(context, event.get("event_type", ""), event)
