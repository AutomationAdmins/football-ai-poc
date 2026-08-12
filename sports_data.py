"""
Sports data adapter — retrieves enriched CSV context from GCS and reshapes it
into the legacy format expected by editorial_context.py and prompt_builder.py.
"""

import copy

from event_lookup import enrich_event
from gcs_data_store import get_data_store


def _safe_int(val) -> int:
    """Convert a value to int, returning 0 on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _safe_float(val) -> float:
    """Convert a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

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
            # Only default to 0 if field was never populated from CSV data
            current = player_stats.get(field)
            if current is None:
                player_stats[field] = 1
            else:
                player_stats[field] = _safe_int(current) + 1

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
            current = team_stats.get(field)
            if current is None:
                team_stats[field] = 1
            else:
                team_stats[field] = _safe_int(current) + 1

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
        raw = enriched["player_season_stats"]
        player_data.update(raw)
        # Map CSV column names → editorial_context expected field names
        if "Gls" in raw and "season_goals" not in player_data:
            player_data["season_goals"] = _safe_int(raw["Gls"])
        if "Ast" in raw and "season_assists" not in player_data:
            player_data["season_assists"] = _safe_int(raw["Ast"])
        if "MP" in raw:
            player_data["season_appearances"] = _safe_int(raw["MP"])
        if "G+A" in raw:
            player_data["season_goal_involvements"] = _safe_int(raw["G+A"])
        if "Gls_per90" in raw:
            player_data["goals_per_90"] = _safe_float(raw["Gls_per90"])
    if enriched.get("player_club_summary"):
        raw_club = enriched["player_club_summary"]
        player_data.update(raw_club)
        # Map club summary fields (career totals at club)
        if "All Competitions Gls" in raw_club:
            career_goals = _safe_int(raw_club["All Competitions Gls"])
            player_data["career_goals_at_club"] = career_goals
            # Compute milestone proximity
            for milestone in [50, 100, 150, 200, 250]:
                if career_goals < milestone:
                    player_data["next_milestone"] = f"{milestone} career goals for {team_name}"
                    player_data["goals_to_next_milestone"] = milestone - career_goals
                    break
        if "Domestic Leagues Gls" in raw_club:
            player_data["league_goals_at_club"] = _safe_int(raw_club["Domestic Leagues Gls"])
    if enriched.get("player_vs_opponent"):
        vs_opp = enriched["player_vs_opponent"]
        player_data["vs_opponent"] = vs_opp
        # Map opponent-specific goals for editorial_context
        opp_slug = opponent_name.lower().replace(" ", "_")
        if "Gls" in vs_opp:
            player_data[f"goals_vs_{opp_slug}_career"] = _safe_int(vs_opp["Gls"])
        if "Ast" in vs_opp:
            player_data[f"assists_vs_{opp_slug}_career"] = _safe_int(vs_opp["Ast"])
        if "MP" in vs_opp:
            player_data[f"appearances_vs_{opp_slug}"] = _safe_int(vs_opp["MP"])
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
        streak_data = enriched["player_scoring_streak"]
        player_data["scoring_streak"] = streak_data
        # Extract consecutive scoring matches from streak data
        if isinstance(streak_data, dict):
            if "longest_scoring_streak_games" in streak_data:
                player_data["consecutive_scoring_matches"] = _safe_int(streak_data["longest_scoring_streak_games"])
        elif isinstance(streak_data, list) and streak_data:
            # Take the most recent/longest streak
            best = max(streak_data, key=lambda s: _safe_int(s.get("longest_scoring_streak_games", 0)))
            player_data["consecutive_scoring_matches"] = _safe_int(best.get("longest_scoring_streak_games", 0))
    if enriched.get("player_shot_conversion"):
        player_data["shot_conversion"] = enriched["player_shot_conversion"]
    if player_data:
        player_data["league"] = league_name
        context["player_stats"] = {player_name: player_data}

    # ── Team stats ──
    team_data: dict = {}
    if enriched.get("team_vs_opponent_record"):
        raw_opp = enriched["team_vs_opponent_record"]
        team_data.update(raw_opp)
        # Map opponent record fields
        if "Wins" in raw_opp:
            team_data["wins_vs_opponent"] = _safe_int(raw_opp["Wins"])
        if "Draws" in raw_opp:
            team_data["draws_vs_opponent"] = _safe_int(raw_opp["Draws"])
        if "Losses" in raw_opp:
            team_data["losses_vs_opponent"] = _safe_int(raw_opp["Losses"])
        if "Goals For" in raw_opp:
            team_data["goals_for_vs_opponent"] = _safe_int(raw_opp["Goals For"])
        if "Goals Against" in raw_opp:
            team_data["goals_against_vs_opponent"] = _safe_int(raw_opp["Goals Against"])
        if "Goal Difference" in raw_opp:
            gd = raw_opp["Goal Difference"]
            if isinstance(gd, str) and gd.startswith("+"):
                gd = gd[1:]
            team_data["goal_difference"] = _safe_int(gd)
    if enriched.get("team_league_history"):
        raw_league = enriched["team_league_history"]
        team_data.update(raw_league)
        # Map league history fields
        if "League Rank" in raw_league and "league_position" not in team_data:
            team_data["league_position"] = raw_league["League Rank"]
        if "Points" in raw_league and "points" not in team_data:
            team_data["points"] = _safe_int(raw_league["Points"])
        if "Top Team Scorer" in raw_league:
            team_data["top_scorer"] = raw_league["Top Team Scorer"]
        if "Goals For" in raw_league and "goals_scored_this_season" not in team_data:
            team_data["goals_scored_this_season"] = _safe_int(raw_league["Goals For"])
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
