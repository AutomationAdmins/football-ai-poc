"""
Event Context Retrieval Module
-------------------------------
Given a match event (goal, assist, card, etc.), retrieves all relevant contextual
data from CSV files stored in GCS (or local fallback): player stats, H2H records,
fixture history, match details, and fixture leaders.

Usage (as a Python module inside this repo):
    from event_lookup import enrich_event
    result = enrich_event({"event": "GOAL", "player": "Erling Haaland", ...})
"""

import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from gcs_data_store import GCSDataStore, get_data_store


# ─── Utilities ────────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize a player/team name for matching: lowercase, strip accents, strip whitespace."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.strip().lower()


def parse_date(date_str: str) -> Optional[str]:
    """Parse various date formats into ISO format (YYYY-MM-DD)."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def get_season_from_date(date_str: str) -> dict[str, str]:
    """Derive football season identifiers from a date."""
    iso = parse_date(date_str)
    if not iso:
        return {}
    dt = datetime.strptime(iso, "%Y-%m-%d")
    if dt.month >= 8:
        start = dt.year
    else:
        start = dt.year - 1
    end = start + 1
    return {
        "full": f"{start}-{end}",
        "start_year": str(start),
        "hyphenated": f"{start}-{end}",
    }


def name_matches(a: str, b: str) -> bool:
    """Check if two names match after normalization."""
    return normalize_name(a) == normalize_name(b)


TEAM_ALIASES = {
    "manchester united": ["manchester utd", "man united", "man utd"],
    "manchester utd": ["manchester united", "man united", "man utd"],
    "manchester city": ["man city"],
    "man city": ["manchester city"],
}

_BIG_6 = frozenset(["arsenal", "chelsea", "liverpool", "manchester united",
                     "manchester utd", "man utd", "tottenham hotspur",
                     "tottenham", "spurs", "manchester city", "man city"])

_MINUTE_BANDS = [(0, 15, "0-15"), (16, 30, "16-30"), (31, 45, "31-45"),
                 (46, 60, "46-60"), (61, 75, "61-75"), (76, 90, "76-90")]


def _minute_to_band(minute: int) -> str:
    """Map a match minute to a band label."""
    for lo, hi, label in _MINUTE_BANDS:
        if lo <= minute <= hi:
            return label
    return "90+"


def team_name_matches(a: str, b: str) -> bool:
    """Check if two team names refer to the same team (handles aliases)."""
    na, nb = normalize_name(a), normalize_name(b)
    if na == nb:
        return True
    aliases_a = TEAM_ALIASES.get(na, [])
    if nb in [normalize_name(x) for x in aliases_a]:
        return True
    aliases_b = TEAM_ALIASES.get(nb, [])
    if na in [normalize_name(x) for x in aliases_b]:
        return True
    return False


def team_slug(team_name: str) -> str:
    """Convert team name to slug used in folder/file names."""
    return normalize_name(team_name).replace(" ", "_")


def _first_match(df: pd.DataFrame, col: str, value: str) -> Optional[dict]:
    """Vectorized single-row lookup: return first row where col == value, or None."""
    mask = df[col].astype(str).str.strip() == value
    matched = df.loc[mask]
    if matched.empty:
        return None
    return matched.iloc[0].dropna().to_dict()


def _first_match_in(df: pd.DataFrame, col: str, values: set[str]) -> Optional[dict]:
    """Vectorized single-row lookup: return first row where col value is in the set."""
    mask = df[col].astype(str).str.strip().isin(values)
    matched = df.loc[mask]
    if matched.empty:
        return None
    return matched.iloc[0].dropna().to_dict()


def _all_matches(df: pd.DataFrame, col: str, value: str) -> list[dict]:
    """Return all rows where col == value as list of dicts."""
    mask = df[col].astype(str).str.strip() == value
    return [r.dropna().to_dict() for _, r in df.loc[mask].iterrows()]


def _get_date_col(df: pd.DataFrame) -> Optional[str]:
    if "Date" in df.columns:
        return "Date"
    if "date" in df.columns:
        return "date"
    return None


def _get_season_col(df: pd.DataFrame) -> Optional[str]:
    if "Season" in df.columns:
        return "Season"
    if "season" in df.columns:
        return "season"
    return None


# ─── Lookup Functions ─────────────────────────────────────────────────────────

def lookup_match_details(store: GCSDataStore, date: str, team: str, opponent: str) -> Optional[dict]:
    """Find the match in derby_matches.csv by date and teams."""
    iso_date = parse_date(date)
    if not iso_date:
        return None
    matches_files = store.find_files("derby_matches.csv")
    nt, no = normalize_name(team), normalize_name(opponent)
    for key, df in matches_files:
        if "date" not in df.columns:
            continue
        mask = df["date"].astype(str).str.strip() == iso_date
        for _, row in df.loc[mask].iterrows():
            teams_in_row = {normalize_name(str(row.get("home_team", ""))),
                            normalize_name(str(row.get("away_team", "")))}
            if nt in teams_in_row and no in teams_in_row:
                return row.dropna().to_dict()
    return None


def lookup_player_goal_log(player_files: list, date: str, minute: Optional[int] = None) -> Optional[dict]:
    """Find a specific goal entry from the player's goal log."""
    iso_date = parse_date(date)
    if not iso_date:
        return None
    for key, df in player_files:
        if "goal_log" not in key.lower():
            continue
        date_col = _get_date_col(df)
        if not date_col:
            continue
        mask = df[date_col].astype(str).str.strip() == iso_date
        candidates = df.loc[mask]
        if candidates.empty:
            continue
        if minute is not None:
            min_col = "Minute" if "Minute" in df.columns else "minute"
            if min_col in df.columns:
                for _, row in candidates.iterrows():
                    row_min = str(row.get(min_col, ""))
                    try:
                        base_min = int(row_min.split("+")[0])
                    except (ValueError, TypeError):
                        base_min = None
                    if base_min == minute or row_min == str(minute):
                        return row.dropna().to_dict()
        return candidates.iloc[0].dropna().to_dict()
    return None


def lookup_player_assist_log(player_files: list, date: str, minute: Optional[int] = None) -> Optional[dict]:
    """Find a specific assist entry from the player's assist log."""
    iso_date = parse_date(date)
    if not iso_date:
        return None
    for key, df in player_files:
        if "assist_log" not in key.lower():
            continue
        date_col = _get_date_col(df)
        if not date_col:
            continue
        mask = df[date_col].astype(str).str.strip() == iso_date
        candidates = df.loc[mask]
        if candidates.empty:
            continue
        if minute is not None:
            min_col = "Minute" if "Minute" in df.columns else "minute"
            if min_col in df.columns:
                for _, row in candidates.iterrows():
                    row_min = str(row.get(min_col, ""))
                    try:
                        base_min = int(row_min.split("+")[0])
                    except (ValueError, TypeError):
                        base_min = None
                    if base_min == minute or row_min == str(minute):
                        return row.dropna().to_dict()
        return candidates.iloc[0].dropna().to_dict()
    return None


def lookup_player_season_stats(player_files: list, date: str) -> Optional[dict]:
    """Get the player's standard stats for the season containing the given date.
    Prefers standard_stats_with_shooting over plain standard_stats."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    # Sort so _with_shooting comes first (reverse alpha puts 'w' before 's')
    sorted_files = sorted(player_files, key=lambda x: x[0], reverse=True)
    for key, df in sorted_files:
        if "standard_stats" not in key.lower():
            continue
        season_col = _get_season_col(df)
        if not season_col:
            continue
        result = _first_match_in(df, season_col, season_variants)
        if result:
            return result
    return None


def lookup_player_club_summary(player_files: list, date: str) -> Optional[dict]:
    """Get the player's club summary for the relevant season."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    for key, df in player_files:
        if "club_summary" not in key.lower():
            continue
        season_col = _get_season_col(df)
        if not season_col:
            continue
        result = _first_match_in(df, season_col, season_variants)
        if result:
            return result
    return None


def lookup_player_vs_opponent(team_files: list, player: str, opponent: str) -> Optional[dict]:
    """Get the player's head-to-head record vs the opponent."""
    opp_norm = normalize_name(opponent)
    for key, df in team_files:
        if "players_vs" not in key.lower():
            continue
        opp_slug = team_slug(opponent)
        if opp_slug.replace("_", "") not in key.lower().replace("_", "").replace(" ", ""):
            opp_parts = opp_norm.split()
            if not any(part in key.lower() for part in opp_parts):
                continue
        player_col = "Player" if "Player" in df.columns else "player"
        if player_col not in df.columns:
            continue
        norm_vals = df[player_col].astype(str).apply(normalize_name)
        mask = norm_vals == normalize_name(player)
        matched = df.loc[mask]
        if not matched.empty:
            return matched.iloc[0].dropna().to_dict()
    return None


def lookup_team_vs_opponent(team_files: list, opponent: str) -> Optional[dict]:
    """Get the team's overall record vs the opponent."""
    for key, df in team_files:
        if "vs_opponents_records" not in key.lower():
            continue
        name_col = None
        for col in df.columns:
            if "club" in col.lower() or "opponent" in col.lower() or "name" in col.lower():
                name_col = col
                break
        if not name_col:
            continue
        norm_vals = df[name_col].astype(str).apply(normalize_name)
        mask = norm_vals == normalize_name(opponent)
        matched = df.loc[mask]
        if not matched.empty:
            return matched.iloc[0].dropna().to_dict()
    return None


def lookup_fixture_leaders(team_files: list) -> dict[str, list[dict]]:
    """Get fixture leaders (goals, assists, appearances, minutes) from the team folder."""
    leaders: dict[str, list[dict]] = {}
    for key, df in team_files:
        if "fixture_leaders" not in key.lower():
            continue
        category = None
        if "goals" in key.lower():
            category = "goals"
        elif "assists" in key.lower():
            category = "assists"
        elif "appearances" in key.lower():
            category = "appearances"
        elif "minutes" in key.lower():
            category = "minutes"
        if category:
            leaders[category] = df.head(10).to_dict(orient="records")
    return leaders


def lookup_team_league_history(team_files: list, date: str) -> Optional[dict]:
    """Get the team's league history entry for the season containing the date."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    for key, df in team_files:
        if "premier_league_history" not in key.lower():
            continue
        season_col = _get_season_col(df)
        if not season_col:
            continue
        result = _first_match_in(df, season_col, season_variants)
        if result:
            return result
    return None


def lookup_derby_events(store: GCSDataStore, date: str) -> list[dict]:
    """Get all derby events for a given date."""
    iso_date = parse_date(date)
    if not iso_date:
        return []
    events_files = store.find_files("derby_events.csv")
    results = []
    for key, df in events_files:
        if "match_id" not in df.columns:
            continue
        mask = df["match_id"].astype(str).str.startswith(iso_date)
        results.extend(df.loc[mask].apply(lambda r: r.dropna().to_dict(), axis=1).tolist())
    return results


def lookup_head_to_head_matches(store: GCSDataStore) -> list[dict]:
    """Get head-to-head match history between two teams."""
    h2h_files = store.find_files("head_to_head_matches.csv")
    results = []
    for key, df in h2h_files:
        results.extend(df.head(20).to_dict(orient="records"))
    return results


def lookup_derby_fixture_leaders(store: GCSDataStore) -> list[dict]:
    """Get derby fixture leaders (top scorers/assists in derby history)."""
    files = store.find_files("fixture_leaders.csv")
    results = []
    for key, df in files:
        if "derby" in key.lower() or "manchester_derby" in key.lower():
            results.extend(df.head(10).to_dict(orient="records"))
    return results


# ─── New Lookup Functions (player analytics & team context) ───────────────────

def lookup_player_minute_band(player_files: list, minute: Optional[int]) -> Optional[dict]:
    """Return the player's goal-scoring record for the minute band matching the event."""
    if minute is None:
        return None
    band = _minute_to_band(minute)
    for key, df in player_files:
        if "goals_by_minute_band" not in key.lower():
            continue
        if "minute_band" not in df.columns:
            continue
        result = _first_match(df, "minute_band", band)
        if result:
            return result
    return None


def lookup_player_home_away_splits(player_files: list, venue: str) -> Optional[dict]:
    """Return Home or Away split row based on venue."""
    if not venue:
        return None
    venue_label = "Home" if venue.lower() == "home" else "Away"
    for key, df in player_files:
        if "home_away_splits" not in key.lower():
            continue
        if "venue" not in df.columns:
            continue
        result = _first_match(df, "venue", venue_label)
        if result:
            return result
    return None


def lookup_player_vs_big6(player_files: list, opponent: str) -> Optional[dict]:
    """If opponent is Big 6, return the player's specific record vs them."""
    if not opponent or normalize_name(opponent) not in _BIG_6:
        return None
    opp_norm = normalize_name(opponent)
    for key, df in player_files:
        if "goals_vs_big6" not in key.lower():
            continue
        if "opponent" not in df.columns:
            continue
        norm_vals = df["opponent"].astype(str).apply(normalize_name)
        mask = norm_vals == opp_norm
        # Also try partial match (e.g. "Manchester United" vs "manchester utd")
        if not mask.any():
            mask = norm_vals.apply(lambda x: team_name_matches(x, opp_norm))
        matched = df.loc[mask]
        if not matched.empty:
            return matched.iloc[0].dropna().to_dict()
    return None


def lookup_player_scoring_streak(player_files: list, date: str) -> Optional[dict]:
    """Return the current season's longest scoring streak."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    for key, df in player_files:
        if "scoring_streaks_summary" not in key.lower():
            continue
        season_col = _get_season_col(df)
        if not season_col:
            continue
        result = _first_match_in(df, season_col, season_variants)
        if result:
            return result
    return None


def lookup_player_shot_conversion(player_files: list, date: str) -> Optional[dict]:
    """Return shooting efficiency for the current season + career total."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    for key, df in player_files:
        if "shot_conversion" not in key.lower():
            continue
        season_col = _get_season_col(df)
        if not season_col:
            continue
        # Get season row
        season_row = _first_match_in(df, season_col, season_variants)
        # Get total row
        total_row = _first_match(df, season_col, "Total")
        if season_row or total_row:
            combined: dict[str, Any] = {}
            if season_row:
                combined["current_season"] = season_row
            if total_row:
                combined["career_total"] = total_row
            return combined
    return None


def lookup_team_recent_form(team_files: list) -> Optional[dict]:
    """Return last-5 form string, points, and the individual match rows."""
    for key, df in team_files:
        if "recent_form" not in key.lower():
            continue
        if df.empty:
            continue
        first_row = df.iloc[0]
        form = str(first_row.get("form_last_5", ""))
        pts = first_row.get("points_last_5", "")
        matches = df.to_dict(orient="records")
        return {"form_last_5": form, "points_last_5": pts, "matches": matches}
    return None


def lookup_team_scoring_streaks(team_files: list) -> Optional[dict]:
    """Return the longest scoring streak and the most recent streak."""
    for key, df in team_files:
        if "scoring_streaks" not in key.lower():
            continue
        if df.empty:
            continue
        result: dict[str, Any] = {}
        # Longest streak
        if "is_longest_streak" in df.columns:
            longest = df.loc[df["is_longest_streak"].astype(str).str.upper() == "Y"]
            if not longest.empty:
                result["longest"] = longest.iloc[0].dropna().to_dict()
        # Most recent streak (last row)
        result["most_recent"] = df.iloc[-1].dropna().to_dict()
        if result:
            return result
    return None


def lookup_league_table(store: GCSDataStore, team: str, opponent: str) -> Optional[dict]:
    """Return both teams' league table positions."""
    table_files = store.find_files("points_table.csv")
    if not table_files:
        return None
    nt, no = normalize_name(team), normalize_name(opponent)
    for key, df in table_files:
        if "Team" not in df.columns and "team" not in df.columns:
            continue
        team_col = "Team" if "Team" in df.columns else "team"
        norm_vals = df[team_col].astype(str).apply(normalize_name)
        result: dict[str, Any] = {}
        # Find team row (with alias matching)
        for idx, nv in norm_vals.items():
            if nv == nt or team_name_matches(nv, nt):
                result["team_standing"] = df.loc[idx].dropna().to_dict()
                break
        # Find opponent row
        for idx, nv in norm_vals.items():
            if nv == no or team_name_matches(nv, no):
                result["opponent_standing"] = df.loc[idx].dropna().to_dict()
                break
        if result:
            return result
    return None


# ─── Main Enrichment Function ────────────────────────────────────────────────

def enrich_event(event: dict[str, Any], store: Optional[GCSDataStore] = None) -> dict[str, Any]:
    """
    Given a match event dict, retrieve all relevant contextual data from GCS CSVs.

    Expected event keys:
        - event_type: str (GOAL, ASSIST, CARD, etc.)  [or 'event' for backward compat]
        - player: str
        - team: str
        - opponent: str
        - date: str (any common format, optional)
        - minutes / minute: int (optional)
        - league: str (optional)
        - score: str (optional)

    Returns a dict with enriched data sections.
    """
    if store is None:
        store = get_data_store()

    player = event.get("player") or ""
    team = event.get("team") or ""
    opponent = event.get("opponent") or ""
    date = event.get("date") or ""
    minute = event.get("minutes") or event.get("minute")
    event_type = (event.get("event_type") or event.get("event", "")).upper()

    # ── Cache file lists once per call ──
    player_files = store.find_player_files(player) if player else []
    team_files = store.find_team_files(team) if team else []
    opponent_files = store.find_team_files(opponent) if opponent else []

    # Derive venue from match_details or best guess
    match_details = lookup_match_details(store, date, team, opponent)
    venue = ""
    if match_details:
        home_team = str(match_details.get("home_team", ""))
        if team_name_matches(home_team, team):
            venue = "Home"
        else:
            venue = "Away"

    result: dict[str, Any] = {
        "input_event": event,
        # Existing lookups
        "match_details": match_details,
        "player_goal_log_entry": None,
        "player_assist_log_entry": None,
        "player_season_stats": None,
        "player_club_summary": None,
        "player_vs_opponent": None,
        "team_vs_opponent_record": None,
        "opponent_vs_team_record": None,
        "fixture_leaders": {},
        "team_league_history": None,
        "opponent_league_history": None,
        "related_derby_events": [],
        "head_to_head_matches": [],
        "derby_fixture_leaders": [],
        # New lookups
        "player_minute_band": None,
        "player_home_away_splits": None,
        "player_vs_big6": None,
        "player_scoring_streak": None,
        "player_shot_conversion": None,
        "team_recent_form": None,
        "team_scoring_streaks": None,
        "league_table": None,
    }

    # ── Player event logs ──
    if player:
        if event_type == "GOAL":
            result["player_goal_log_entry"] = lookup_player_goal_log(player_files, date, minute)
        elif event_type == "ASSIST":
            result["player_assist_log_entry"] = lookup_player_assist_log(player_files, date, minute)
        else:
            result["player_goal_log_entry"] = lookup_player_goal_log(player_files, date, minute)
            result["player_assist_log_entry"] = lookup_player_assist_log(player_files, date, minute)

        # Player season stats & club summary
        result["player_season_stats"] = lookup_player_season_stats(player_files, date)
        result["player_club_summary"] = lookup_player_club_summary(player_files, date)

        # Player H2H vs opponent
        result["player_vs_opponent"] = lookup_player_vs_opponent(team_files, player, opponent)

        # New player analytics
        result["player_minute_band"] = lookup_player_minute_band(player_files, minute)
        result["player_home_away_splits"] = lookup_player_home_away_splits(player_files, venue)
        result["player_vs_big6"] = lookup_player_vs_big6(player_files, opponent)
        result["player_scoring_streak"] = lookup_player_scoring_streak(player_files, date)
        result["player_shot_conversion"] = lookup_player_shot_conversion(player_files, date)

    # ── Team records (always run) ──
    result["team_vs_opponent_record"] = lookup_team_vs_opponent(team_files, opponent)
    result["opponent_vs_team_record"] = lookup_team_vs_opponent(opponent_files, team)

    # Fixture leaders (from both sides)
    team_leaders = lookup_fixture_leaders(team_files)
    opponent_leaders = lookup_fixture_leaders(opponent_files)
    result["fixture_leaders"] = {"team": team_leaders, "opponent": opponent_leaders}

    # Team league history for the season
    result["team_league_history"] = lookup_team_league_history(team_files, date)
    result["opponent_league_history"] = lookup_team_league_history(opponent_files, date)

    # New team/league analytics
    result["team_recent_form"] = lookup_team_recent_form(team_files)
    result["team_scoring_streaks"] = lookup_team_scoring_streaks(team_files)
    result["league_table"] = lookup_league_table(store, team, opponent)

    # Derby-specific data
    result["related_derby_events"] = lookup_derby_events(store, date)
    result["head_to_head_matches"] = lookup_head_to_head_matches(store)
    result["derby_fixture_leaders"] = lookup_derby_fixture_leaders(store)

    # Remove None/empty values for cleaner output
    result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}

    return result


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    """Read event JSON from stdin or first CLI argument, print enriched result."""
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r") as f:
            event = json.load(f)
    else:
        raw = sys.stdin.read().strip()
        if not raw:
            print("Usage: echo '{\"event_type\": \"GOAL\", ...}' | python event_lookup.py", file=sys.stderr)
            sys.exit(1)
        event = json.loads(raw)

    result = enrich_event(event)
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
