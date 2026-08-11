"""
Sports data adapter — retrieves enriched CSV context from GCS and reshapes it
into the legacy format expected by editorial_context.py and prompt_builder.py.
"""

import copy

from event_lookup import enrich_event
from gcs_data_store import get_data_store

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


def _reshape_enriched(enriched: dict, event: dict) -> dict:
    """
    Reshape the output from enrich_event() into the legacy stats_context format:
        {league_stats, fixture_stats, player_stats, team_stats, fixture_lookup}
    """
    context: dict = {}

    player_name = event.get("player", "unknown")
    team_name = event.get("team", "unknown")
    opponent_name = event.get("opponent", "unknown")
    league_name = event.get("league", "Premier League")

    # ── Player stats ──
    player_data: dict = {}
    if enriched.get("player_season_stats"):
        player_data.update(enriched["player_season_stats"])
    if enriched.get("player_club_summary"):
        player_data.update(enriched["player_club_summary"])
    if enriched.get("player_vs_opponent"):
        player_data["vs_opponent"] = enriched["player_vs_opponent"]
    if enriched.get("player_goal_log_entry"):
        player_data["latest_goal"] = enriched["player_goal_log_entry"]
    if enriched.get("player_assist_log_entry"):
        player_data["latest_assist"] = enriched["player_assist_log_entry"]
    if enriched.get("player_minute_band"):
        player_data["minute_band_context"] = enriched["player_minute_band"]
    if enriched.get("player_home_away_splits"):
        player_data["home_away_splits"] = enriched["player_home_away_splits"]
    if enriched.get("player_vs_big6"):
        player_data["vs_big6"] = enriched["player_vs_big6"]
    if enriched.get("player_scoring_streak"):
        player_data["scoring_streak"] = enriched["player_scoring_streak"]
    if enriched.get("player_shot_conversion"):
        player_data["shot_conversion"] = enriched["player_shot_conversion"]
    if player_data:
        player_data["league"] = league_name
        context["player_stats"] = {player_name: player_data}

    # ── Team stats ──
    team_data: dict = {}
    if enriched.get("team_vs_opponent_record"):
        team_data.update(enriched["team_vs_opponent_record"])
    if enriched.get("team_league_history"):
        team_data.update(enriched["team_league_history"])
    if enriched.get("team_recent_form"):
        team_data["recent_form"] = enriched["team_recent_form"]
    if enriched.get("team_scoring_streaks"):
        team_data["scoring_streaks"] = enriched["team_scoring_streaks"]
    if team_data:
        team_data["league"] = league_name
        context["team_stats"] = {team_name: team_data}

    # ── Fixture stats ──
    fixture_data: dict = {}
    if enriched.get("match_details"):
        fixture_data.update(enriched["match_details"])
    fixture_data["home_team"] = team_name
    fixture_data["away_team"] = opponent_name
    fixture_data["competition"] = league_name

    # Head-to-head
    if enriched.get("head_to_head_matches"):
        fixture_data["head_to_head"] = enriched["head_to_head_matches"]
    if enriched.get("derby_fixture_leaders"):
        fixture_data["derby_fixture_leaders"] = enriched["derby_fixture_leaders"]

    # Fixture leaders
    if enriched.get("fixture_leaders"):
        fixture_data["fixture_leaders"] = enriched["fixture_leaders"]

    # Derby events
    if enriched.get("related_derby_events"):
        fixture_data["is_derby"] = True
        fixture_data["derby_events"] = enriched["related_derby_events"]

    fixture_key = f"{team_name} vs {opponent_name}"
    context["fixture_stats"] = {fixture_key: fixture_data}
    context["fixture_lookup"] = {"selected_fixture": {"name": fixture_key}}

    # ── League stats ──
    league_data: dict = {}
    if enriched.get("team_league_history"):
        league_data["team_history"] = enriched["team_league_history"]
    if enriched.get("opponent_league_history"):
        league_data["opponent_history"] = enriched["opponent_league_history"]
    if enriched.get("league_table"):
        league_data["standings"] = enriched["league_table"]
    if league_data:
        context["league_stats"] = {league_name: league_data}

    return context


def get_context(event: dict) -> dict:
    """
    Main entry point — called by app.py.
    Enriches the event using CSV data from GCS and returns the legacy-shaped context.
    """
    store = get_data_store()
    enriched = enrich_event(event, store)
    context = _reshape_enriched(enriched, event)

    # Apply live event increments
    return _apply_increments(context, event.get("event_type", ""), event)
