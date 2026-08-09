"""
Match State Tracker — builds live match context from event history.
Tracks goals by player, hat-tricks, score progression, and narrative flow.
"""

from collections import defaultdict
from typing import Any


def build_match_state(match_history: list[dict], current_event: dict) -> dict:
    """
    Build comprehensive match state from event history.
    Returns live stats: goals by player today, hat-tricks, score changes, etc.
    """
    state = {
        "goals_by_player": defaultdict(int),
        "assists_by_player": defaultdict(int),
        "red_cards": [],
        "var_decisions_count": 0,
        "score_progression": [],  # [(minute, score, event_type, player)]
        "total_goals": 0,
        "current_minute": 0,
        "xG_cumulative": {"home": 0.0, "away": 0.0},
    }

    home_team = None
    away_team = None

    # Process all previous events plus current
    all_events = match_history + [current_event]

    for event in all_events:
        event_type = event.get("event_type", "").upper()
        player = event.get("player")
        minute = event.get("minute", 0)
        score = event.get("score")
        team = event.get("team")
        opponent = event.get("opponent")

        # Establish home/away teams from first event
        if home_team is None and team and opponent:
            # Assume team in first event is home (in real system, get from fixture data)
            home_team = team
            away_team = opponent

        state["current_minute"] = max(state["current_minute"], minute)

        if event_type == "GOAL":
            if player:
                state["goals_by_player"][player] += 1
                state["total_goals"] += 1

            if score:
                state["score_progression"].append({
                    "minute": minute,
                    "score": score,
                    "event_type": event_type,
                    "player": player,
                    "team": team,
                })

            # Track xG if available
            xg_value = event.get("xG", 0.0)
            if team == home_team:
                state["xG_cumulative"]["home"] += xg_value
            else:
                state["xG_cumulative"]["away"] += xg_value

        elif event_type == "RED_CARD":
            if player:
                state["red_cards"].append({
                    "player": player,
                    "team": team,
                    "minute": minute,
                })

        elif event_type == "VAR_DECISION":
            state["var_decisions_count"] += 1

    return dict(state)


def detect_player_performance(player_name: str, match_state: dict, event: dict) -> dict:
    """
    Analyze a player's performance in this match.
    Returns milestones: hat-trick, brace, perfect xG conversion, etc.
    """
    goals_today = match_state["goals_by_player"].get(player_name, 0)

    performance = {
        "goals_today": goals_today,
        "is_hat_trick": goals_today >= 3,
        "is_brace": goals_today == 2,
        "is_first_goal": goals_today == 1,
        "match_winner": False,  # Set by caller based on score
        "xG_for_this_goal": event.get("xG") or 0.0,
    }

    # Check if this was a high-quality chance converted
    xg = event.get("xG") or 0.0
    if xg > 0.5:
        performance["high_quality_chance"] = True
    elif xg < 0.1:
        performance["low_quality_chance_converted"] = True

    return performance


def detect_novelty(match_state: dict, previous_insights: list[dict]) -> dict:
    """
    Identify what's NEW and interesting in the current match state.
    Helps avoid repeating contextual facts shown in earlier events.
    """
    novelty = {
        "new_milestones": [],
        "significant_changes": [],
        "unique_stats": [],
    }

    # Check for hat-tricks
    for player, goals in match_state["goals_by_player"].items():
        if goals == 3:
            novelty["new_milestones"].append(f"HAT-TRICK: {player}")
        elif goals == 2:
            novelty["new_milestones"].append(f"BRACE: {player}")

    # Check for red cards
    if match_state["red_cards"]:
        latest_red = match_state["red_cards"][-1]
        novelty["significant_changes"].append(
            f"RED CARD: {latest_red['player']} sent off at {latest_red['minute']}'"
        )

    # Check score progression for comebacks
    if len(match_state["score_progression"]) >= 2:
        latest_score = match_state["score_progression"][-1]["score"]
        novelty["unique_stats"].append(f"Current score: {latest_score}")

    return novelty


def get_used_insight_lines(match_history: list[dict]) -> set[str]:
    """
    Extract all insight lines already shown in previous events.
    Used for anti-repetition filtering.
    """
    used_lines = set()

    for event in match_history:
        # The insight data might be embedded in the event from Firestore
        insights = event.get("insights", [])
        for insight in insights:
            line = insight.get("line")
            if line:
                used_lines.add(line.strip())

    return used_lines


def filter_duplicate_insights(new_insights: list[dict], used_lines: set[str]) -> list[dict]:
    """
    Remove insights that were already shown.
    Returns only novel insights.
    """
    filtered = []

    for insight in new_insights:
        line = insight.get("line", "").strip()

        # Exact match check
        if line in used_lines:
            continue

        # Semantic similarity check (basic version - checks key phrases)
        is_duplicate = False
        for used_line in used_lines:
            # Check if the core stat is repeated (e.g., "74 pts, 2 in Premier League")
            if _has_significant_overlap(line, used_line):
                is_duplicate = True
                break

        if not is_duplicate:
            filtered.append(insight)
            used_lines.add(line)  # Add to set to prevent duplicates within this batch

    return filtered


def _has_significant_overlap(line1: str, line2: str) -> bool:
    """
    Check if two insight lines contain the same core information.
    Simple heuristic: if >70% of words overlap, consider it duplicate.
    """
    words1 = set(line1.lower().split())
    words2 = set(line2.lower().split())

    if not words1 or not words2:
        return False

    overlap = len(words1 & words2)
    min_length = min(len(words1), len(words2))

    return overlap / min_length > 0.7 if min_length > 0 else False


def build_match_statistics(match_history: list[dict], current_event: dict) -> dict:
    """
    Build comprehensive match statistics for HALF_TIME and FULL_TIME events.
    Aggregates all stats from the match history up to the current moment.
    """
    stats = {
        "goals_by_team": {},
        "goals_by_player": {},
        "scorers": [],  # List of goal scorers with details
        "xG_by_team": {},
        "avg_pass_accuracy_by_team": {},
        "avg_pressure_index_by_team": {},
        "red_cards": [],
        "var_decisions_count": 0,
        "total_goals": 0,
        "score": current_event.get("score", "0-0"),
        "minute": current_event.get("minute", 0),
    }
    
    current_minute = current_event.get("minute", 0)
    home_team = None
    away_team = None
    
    # Track pass accuracy and pressure for averaging
    pass_accuracy_data = defaultdict(list)
    pressure_data = defaultdict(list)
    
    # Process only events UP TO (not including) the current event's minute
    # This ensures HALF_TIME shows only first-half stats, FULL_TIME shows all stats
    for event in match_history:
        event_minute = event.get("minute", 0)
        # Only include events that happened before or at the current moment
        if event_minute > current_minute:
            continue
            
        event_type = event.get("event_type", "").upper()
        player = event.get("player")
        team = event.get("team")
        opponent = event.get("opponent")
        minute = event.get("minute", 0)
        
        # Establish team names
        if home_team is None and team and opponent:
            home_team = team
            away_team = opponent
            stats["goals_by_team"][home_team] = 0
            stats["goals_by_team"][away_team] = 0
            stats["xG_by_team"][home_team] = 0.0
            stats["xG_by_team"][away_team] = 0.0
        
        # Track goals
        if event_type == "GOAL" and team:
            stats["goals_by_team"][team] = stats["goals_by_team"].get(team, 0) + 1
            stats["total_goals"] += 1
            
            if player:
                stats["goals_by_player"][player] = stats["goals_by_player"].get(player, 0) + 1
                stats["scorers"].append({
                    "player": player,
                    "team": team,
                    "minute": minute,
                    "xG": event.get("xG", 0.0),
                })
            
            # Track xG
            xg_value = event.get("xG", 0.0)
            if team:
                stats["xG_by_team"][team] = stats["xG_by_team"].get(team, 0.0) + xg_value
        
        # Track tactical stats
        if event.get("pass_accuracy") is not None and team:
            pass_accuracy_data[team].append(event["pass_accuracy"])
        
        if event.get("pressure_index") is not None and team:
            pressure_data[team].append(event["pressure_index"])
        
        # Track disciplinary
        if event_type == "RED_CARD" and player:
            stats["red_cards"].append({
                "player": player,
                "team": team,
                "minute": minute,
            })
        
        if event_type == "VAR_DECISION":
            stats["var_decisions_count"] += 1
    
    # Calculate averages
    for team, accuracies in pass_accuracy_data.items():
        if accuracies:
            stats["avg_pass_accuracy_by_team"][team] = round(sum(accuracies) / len(accuracies), 1)
    
    for team, pressures in pressure_data.items():
        if pressures:
            stats["avg_pressure_index_by_team"][team] = round(sum(pressures) / len(pressures), 1)
    
    # Add team names for display
    stats["home_team"] = home_team
    stats["away_team"] = away_team
    
    return stats


def format_match_state_for_prompt(match_state: dict) -> str:
    """
    Format match state into a concise summary for LLM prompt.
    """
    lines = []

    if match_state["goals_by_player"]:
        lines.append("Goals scored today:")
        for player, count in sorted(
            match_state["goals_by_player"].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            status = ""
            if count >= 3:
                status = " (HAT-TRICK)"
            elif count == 2:
                status = " (BRACE)"
            lines.append(f"  - {player}: {count}{status}")

    if match_state["red_cards"]:
        lines.append("\nRed cards:")
        for rc in match_state["red_cards"]:
            lines.append(f"  - {rc['player']} ({rc['team']}) at {rc['minute']}'")

    if match_state["score_progression"]:
        lines.append("\nScore progression:")
        for sp in match_state["score_progression"][-5:]:  # Last 5 goals
            lines.append(f"  - {sp['minute']}': {sp['score']} ({sp['player']})")

    lines.append(f"\nCurrent minute: {match_state['current_minute']}'")
    lines.append(f"Total goals: {match_state['total_goals']}")

    return "\n".join(lines)
