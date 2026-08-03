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


_GOAL_TYPE_LABELS = {
    "equaliser": "equaliser",
    "go_ahead_goal": "go-ahead goal",
    "extends_lead": "goal extending the lead",
    "extends_large_lead": "goal extending a large lead",
}


def build_commentator_facts(
    event: dict,
    fixture: dict,
    team: dict,
    player: dict,
    league: dict,
    live_state: dict,
    editorial: dict,
) -> dict:
    """
    Pre-compute broadcast-ready fact lines from grounded context.
    Gives the LLM a clear stat pack to phrase into on-air lines.
    """

    facts = {}

    player_name = event.get("player")
    team_name = event.get("team")
    opponent = event.get("opponent")
    minute = event.get("minute")
    score = event.get("score")
    goal_type = live_state.get("goal_type", "unknown")
    gt_label = _GOAL_TYPE_LABELS.get(goal_type, "goal")

    if minute and score and team_name and opponent:
        facts["what_happened"] = (
            f"{minute}' {gt_label} — {score} ({team_name} vs {opponent})"
        )

    facts["goal_type"] = goal_type
    facts["minute"] = minute
    facts["score"] = score
    facts["player"] = player_name
    facts["team"] = team_name
    facts["opponent"] = opponent
    facts["competition"] = editorial.get("competition")

    player_bits = []
    if player.get("season_goals") is not None:
        player_bits.append(f"{player['season_goals']} goals this season")
    if player.get("season_assists") is not None:
        player_bits.append(f"{player['season_assists']} assists this season")
    if player.get("consecutive_scoring_matches"):
        player_bits.append(
            f"{player['consecutive_scoring_matches']} consecutive scoring matches"
        )
    elif player.get("consecutive_goal_involvements"):
        player_bits.append(
            f"{player['consecutive_goal_involvements']} consecutive goal involvements"
        )
    if opponent:
        opp_slug = opponent.lower().replace(" ", "_")
        career_key = f"goals_vs_{opp_slug}_career"
        season_key = f"goals_vs_{opp_slug}_this_season"
        if career_key in player:
            player_bits.append(
                f"{player[career_key]} career goals vs {opponent}"
            )
        if season_key in player:
            player_bits.append(
                f"{player[season_key]} vs {opponent} this season"
            )
    if player.get("next_milestone") and player.get("goals_to_next_milestone") is not None:
        player_bits.append(
            f"{player['goals_to_next_milestone']} away from {player['next_milestone']}"
        )
    if player.get("championship_top_scorer_this_season"):
        notes = player.get("notes", "")
        if "top scorer" not in notes.lower():
            player_bits.append("Championship top scorer this season")
    if player.get("notes"):
        player_bits.append(player["notes"])
    if player_bits:
        facts["player_highlight"] = "; ".join(player_bits)

    team_bits = []
    if team.get("league_position") is not None and team.get("points") is not None:
        team_bits.append(
            f"{team['points']} pts, {team['league_position']} in {editorial.get('competition', '')}"
        )
    if team.get("winning_streak"):
        team_bits.append(f"{team['winning_streak']}-game win streak")
    if team.get("home_unbeaten"):
        team_bits.append(f"unbeaten in {team['home_unbeaten']} home games")
    if team.get("goal_difference") is not None:
        team_bits.append(f"+{team['goal_difference']} goal difference")
    if team.get("years_out_of_premier_league"):
        team_bits.append(
            f"{team['years_out_of_premier_league']} seasons outside the Premier League"
        )
    if team_bits:
        facts["team_highlight"] = "; ".join(team_bits)

    is_home = fixture.get("home_team") == team_name
    stakes = fixture.get("stakes_home") if is_home else fixture.get("stakes_away")
    if stakes:
        facts["stakes_line"] = stakes

    opp_stakes = fixture.get("stakes_away") if is_home else fixture.get("stakes_home")
    if opp_stakes and opponent:
        facts["opponent_line"] = f"{opponent}: {opp_stakes}"

    if league.get("title_race"):
        tr = league["title_race"]
        facts["title_race"] = (
            f"{tr.get('chasers')} on {tr.get('chasers_points')} pts, "
            f"{tr.get('points_gap')} behind {tr.get('leaders')} ({tr.get('leaders_points')} pts)"
        )
        if tr.get("cross_impact"):
            facts["cross_match"] = tr["cross_impact"]

    if league.get("automatic_promotion"):
        ap = league["automatic_promotion"]
        if ap.get("cross_impact"):
            facts["promotion_stakes"] = ap["cross_impact"]

    if league.get("champions_league_battle"):
        cl = league["champions_league_battle"]
        if cl.get("cross_impact"):
            facts["champions_league_stakes"] = cl["cross_impact"]

    if fixture.get("venue"):
        facts["venue"] = fixture["venue"]
    if fixture.get("is_derby"):
        facts["derby"] = fixture.get("derby_name") or "derby match"
    if fixture.get("promotion_consequence"):
        facts["promotion_consequence"] = fixture["promotion_consequence"]

    h2h_leeds = fixture.get("head_to_head_goals_leeds")
    h2h_sunderland = fixture.get("head_to_head_goals_sunderland")
    if h2h_leeds is not None and h2h_sunderland is not None:
        facts["head_to_head"] = (
            f"Head-to-head goals: {fixture.get('home_team')} {h2h_leeds}, "
            f"{fixture.get('away_team')} {h2h_sunderland}"
        )

    h2h_arsenal = fixture.get("head_to_head_goals_arsenal")
    h2h_chelsea = fixture.get("head_to_head_goals_chelsea")
    if h2h_arsenal is not None and h2h_chelsea is not None:
        facts["head_to_head"] = (
            f"Head-to-head goals: Arsenal {h2h_arsenal}, Chelsea {h2h_chelsea}"
        )

    return facts


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

    context["commentator_facts"] = build_commentator_facts(
        event,
        fixture,
        team,
        player,
        context["league"],
        context["live_editorial_state"],
        editorial,
    )

    return context