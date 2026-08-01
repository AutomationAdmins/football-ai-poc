from copy import deepcopy

def build_live_match_context(event: dict) -> dict:
    """
    Derive objective live match facts from the incoming event.
    No editorial decisions are made here.
    """

    live = {}

    score = event.get("score")

    live["score"] = score
    live["minute"] = event.get("minute")
    live["event_type"] = event.get("event_type")

    live["goal_type"] = "unknown"

    if score:

        try:
            home, away = map(int, score.split("-"))

            goal_difference = abs(home - away)

            if home == away:
                live["goal_type"] = "equaliser"

            elif goal_difference == 1:
                live["goal_type"] = "go_ahead_goal"

            elif goal_difference >= 3:
                live["goal_type"] = "extends_large_lead"

            else:
                live["goal_type"] = "extends_lead"

        except Exception:
            live["goal_type"] = "unknown"

    return live

def build_editorial_context(event: dict, stats_context: dict) -> dict:
    """
    Creates one grounded editorial context by combining

    - Live Opta event
    - FootballEdit historical data

    This function performs NO ranking and NO AI reasoning.
    """

    context = {
        "event": deepcopy(event),
        "league": {},
        "fixture": {},
        "team": {},
        "player": {},
        "editorial_facts": {}
    }

    # ----------------------------------------------------
    # League Context
    # ----------------------------------------------------

    if stats_context.get("league_stats"):
        context["league"] = deepcopy(
            next(iter(stats_context["league_stats"].values()))
        )

    # ----------------------------------------------------
    # Fixture Context
    # ----------------------------------------------------

    if stats_context.get("fixture_stats"):
        context["fixture"] = deepcopy(
            next(iter(stats_context["fixture_stats"].values()))
        )

    # ----------------------------------------------------
    # Team Context
    # ----------------------------------------------------

    if stats_context.get("team_stats"):
        context["team"] = deepcopy(
            next(iter(stats_context["team_stats"].values()))
        )

    # ----------------------------------------------------
    # Player Context
    # ----------------------------------------------------

    if stats_context.get("player_stats"):
        context["player"] = deepcopy(
            next(iter(stats_context["player_stats"].values()))
        )

    # ----------------------------------------------------
    # Editorial Signals
    # ----------------------------------------------------

    fixture = context["fixture"]
    team = context["team"]
    player = context["player"]

    editorial = {}

    #
    # Competition
    #

    editorial["competition"] = fixture.get(
        "competition",
        event.get("league")
    )

    #
    # League Position
    #

    editorial["league_position"] = team.get(
        "league_position"
    )

    #
    # Derby
    #

    editorial["is_derby"] = fixture.get(
        "is_derby",
        False
    )

    editorial["derby_name"] = fixture.get(
        "derby_name"
    )

    #
    # Title Race
    #

    editorial["title_race"] = team.get(
        "title_race",
        False
    )

    editorial["title_decider"] = fixture.get(
        "title_decider",
        False
    )

    #
    # Promotion
    #

    editorial["promotion_decider"] = fixture.get(
        "promotion_decider",
        False
    )

    editorial["promotion_on_the_line"] = team.get(
        "promotion_on_the_line",
        False
    )

    #
    # Champions League
    #

    editorial["champions_league_at_risk"] = team.get(
        "champions_league_at_risk",
        False
    )

    #
    # Big Club
    #

    editorial["big_club_rating"] = team.get(
        "big_club_rating"
    )

    #
    # Milestones
    #

    editorial["next_milestone"] = player.get(
        "next_milestone"
    )

    editorial["goals_to_next_milestone"] = player.get(
        "goals_to_next_milestone"
    )

    #
    # Historical Notes
    #

    editorial["player_notes"] = player.get(
        "notes"
    )

    editorial["team_notes"] = team.get(
        "notes"
    )

    #
    # Cross Match Impact
    #

    editorial["cross_impact"] = (
        fixture.get("cross_impact")
        or team.get("cross_impact")
    )

    #
    # Stakes
    #

    editorial["home_team_stakes"] = fixture.get(
        "stakes_home"
    )

    editorial["away_team_stakes"] = fixture.get(
        "stakes_away"
    )

    #
    # Match Minute
    #

    editorial["minute"] = event.get(
        "minute"
    )

    #
    # Current Score
    #

    editorial["score"] = event.get(
        "score"
    )

    #
    # Event Type
    #

    editorial["event_type"] = event.get(
        "event_type"
    )

    #
    # Player
    #

    editorial["player"] = event.get(
        "player"
    )

    #
    # Team
    #

    editorial["team"] = event.get(
        "team"
    )

    #
    # Opponent
    #

    editorial["opponent"] = event.get(
        "opponent"
    )

    context["editorial_facts"] = editorial
    
    context["live_editorial_state"] = build_live_match_context(event)

    return context