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


# ─── Lookup Functions ─────────────────────────────────────────────────────────

def lookup_match_details(store: GCSDataStore, date: str, team: str, opponent: str) -> Optional[dict]:
    """Find the match in derby_matches.csv by date and teams."""
    iso_date = parse_date(date)
    matches_files = store.find_files("derby_matches.csv")
    for key, df in matches_files:
        if "date" not in df.columns:
            continue
        for _, row in df.iterrows():
            row_date = parse_date(str(row.get("date", "")))
            if row_date != iso_date:
                continue
            home = str(row.get("home_team", ""))
            away = str(row.get("away_team", ""))
            teams_in_row = {normalize_name(home), normalize_name(away)}
            if normalize_name(team) in teams_in_row and normalize_name(opponent) in teams_in_row:
                return row.dropna().to_dict()
    return None


def lookup_player_goal_log(store: GCSDataStore, player: str, date: str, minute: Optional[int] = None) -> Optional[dict]:
    """Find a specific goal entry from the player's goal log."""
    iso_date = parse_date(date)
    player_files = store.find_player_files(player)
    for key, df in player_files:
        if "goal_log" not in key.lower():
            continue
        if "Date" not in df.columns and "date" not in df.columns:
            continue
        date_col = "Date" if "Date" in df.columns else "date"
        for _, row in df.iterrows():
            row_date = parse_date(str(row.get(date_col, "")))
            if row_date != iso_date:
                continue
            if minute is not None:
                row_min = str(row.get("Minute", row.get("minute", "")))
                try:
                    base_min = int(str(row_min).split("+")[0])
                except (ValueError, TypeError):
                    base_min = None
                if base_min is not None and base_min != minute and row_min != str(minute):
                    continue
            return row.dropna().to_dict()
    return None


def lookup_player_assist_log(store: GCSDataStore, player: str, date: str, minute: Optional[int] = None) -> Optional[dict]:
    """Find a specific assist entry from the player's assist log."""
    iso_date = parse_date(date)
    player_files = store.find_player_files(player)
    for key, df in player_files:
        if "assist_log" not in key.lower():
            continue
        if "Date" not in df.columns and "date" not in df.columns:
            continue
        date_col = "Date" if "Date" in df.columns else "date"
        for _, row in df.iterrows():
            row_date = parse_date(str(row.get(date_col, "")))
            if row_date != iso_date:
                continue
            if minute is not None:
                row_min = str(row.get("Minute", row.get("minute", "")))
                try:
                    base_min = int(str(row_min).split("+")[0])
                except (ValueError, TypeError):
                    base_min = None
                if base_min is not None and base_min != minute and row_min != str(minute):
                    continue
            return row.dropna().to_dict()
    return None


def lookup_player_season_stats(store: GCSDataStore, player: str, date: str) -> Optional[dict]:
    """Get the player's standard stats for the season containing the given date."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    player_files = store.find_player_files(player)
    for key, df in player_files:
        if "standard_stats" not in key.lower():
            continue
        if "Season" not in df.columns and "season" not in df.columns:
            continue
        season_col = "Season" if "Season" in df.columns else "season"
        for _, row in df.iterrows():
            row_season = str(row.get(season_col, "")).strip()
            if row_season in season_variants:
                return row.dropna().to_dict()
    return None


def lookup_player_club_summary(store: GCSDataStore, player: str, date: str) -> Optional[dict]:
    """Get the player's club summary for the relevant season."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    player_files = store.find_player_files(player)
    for key, df in player_files:
        if "club_summary" not in key.lower():
            continue
        if "Season" not in df.columns and "season" not in df.columns:
            continue
        season_col = "Season" if "Season" in df.columns else "season"
        for _, row in df.iterrows():
            row_season = str(row.get(season_col, "")).strip()
            if row_season in season_variants:
                return row.dropna().to_dict()
    return None


def lookup_player_vs_opponent(store: GCSDataStore, player: str, team: str, opponent: str) -> Optional[dict]:
    """Get the player's head-to-head record vs the opponent."""
    team_files = store.find_team_files(team)
    for key, df in team_files:
        if "players_vs" not in key.lower():
            continue
        opp_slug = team_slug(opponent)
        if opp_slug.replace("_", "") not in key.lower().replace("_", "").replace(" ", ""):
            opp_parts = normalize_name(opponent).split()
            if not any(part in key.lower() for part in opp_parts):
                continue
        player_col = "Player" if "Player" in df.columns else "player"
        if player_col not in df.columns:
            continue
        for _, row in df.iterrows():
            if name_matches(str(row.get(player_col, "")), player):
                return row.dropna().to_dict()
    return None


def lookup_team_vs_opponent(store: GCSDataStore, team: str, opponent: str) -> Optional[dict]:
    """Get the team's overall record vs the opponent."""
    team_files = store.find_team_files(team)
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
        for _, row in df.iterrows():
            if name_matches(str(row.get(name_col, "")), opponent):
                return row.dropna().to_dict()
    return None


def lookup_fixture_leaders(store: GCSDataStore, team: str) -> dict[str, list[dict]]:
    """Get fixture leaders (goals, assists, appearances, minutes) from the team folder."""
    leaders = {}
    team_files = store.find_team_files(team)
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


def lookup_team_league_history(store: GCSDataStore, team: str, date: str) -> Optional[dict]:
    """Get the team's league history entry for the season containing the date."""
    seasons = get_season_from_date(date)
    if not seasons:
        return None
    season_variants = set(seasons.values())
    team_files = store.find_team_files(team)
    for key, df in team_files:
        if "premier_league_history" not in key.lower():
            continue
        if "Season" not in df.columns and "season" not in df.columns:
            continue
        season_col = "Season" if "Season" in df.columns else "season"
        for _, row in df.iterrows():
            row_season = str(row.get(season_col, "")).strip()
            if row_season in season_variants:
                return row.dropna().to_dict()
    return None


def lookup_derby_events(store: GCSDataStore, date: str, player: Optional[str] = None) -> list[dict]:
    """Get all derby events for a given date (and optionally player)."""
    iso_date = parse_date(date)
    events_files = store.find_files("derby_events.csv")
    results = []
    for key, df in events_files:
        if "match_id" not in df.columns:
            continue
        for _, row in df.iterrows():
            match_id = str(row.get("match_id", ""))
            if iso_date and match_id.startswith(iso_date):
                if player and "player_name" in df.columns:
                    if not name_matches(str(row.get("player_name", "")), player):
                        continue
                results.append(row.dropna().to_dict())
    return results


def lookup_head_to_head_matches(store: GCSDataStore, team: str, opponent: str) -> list[dict]:
    """Get head-to-head match history between two teams."""
    h2h_files = store.find_files("head_to_head_matches.csv")
    results = []
    for key, df in h2h_files:
        # Return all rows — these are already filtered to the fixture pair
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

    player = event.get("player", "")
    team = event.get("team", "")
    opponent = event.get("opponent", "")
    date = event.get("date", "")
    minute = event.get("minutes") or event.get("minute")
    event_type = (event.get("event_type") or event.get("event", "")).upper()

    result: dict[str, Any] = {
        "input_event": event,
        "match_details": None,
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
    }

    # Match details
    result["match_details"] = lookup_match_details(store, date, team, opponent)

    # Player event logs
    if event_type == "GOAL":
        result["player_goal_log_entry"] = lookup_player_goal_log(store, player, date, minute)
    elif event_type == "ASSIST":
        result["player_assist_log_entry"] = lookup_player_assist_log(store, player, date, minute)
    else:
        result["player_goal_log_entry"] = lookup_player_goal_log(store, player, date, minute)
        result["player_assist_log_entry"] = lookup_player_assist_log(store, player, date, minute)

    # Player season stats
    result["player_season_stats"] = lookup_player_season_stats(store, player, date)
    result["player_club_summary"] = lookup_player_club_summary(store, player, date)

    # Player H2H vs opponent
    result["player_vs_opponent"] = lookup_player_vs_opponent(store, player, team, opponent)

    # Team records
    result["team_vs_opponent_record"] = lookup_team_vs_opponent(store, team, opponent)
    result["opponent_vs_team_record"] = lookup_team_vs_opponent(store, opponent, team)

    # Fixture leaders (from both sides)
    team_leaders = lookup_fixture_leaders(store, team)
    opponent_leaders = lookup_fixture_leaders(store, opponent)
    result["fixture_leaders"] = {
        "team": team_leaders,
        "opponent": opponent_leaders,
    }

    # Team league history for the season
    result["team_league_history"] = lookup_team_league_history(store, team, date)
    result["opponent_league_history"] = lookup_team_league_history(store, opponent, date)

    # Derby-specific data
    result["related_derby_events"] = lookup_derby_events(store, date, player=None)
    result["head_to_head_matches"] = lookup_head_to_head_matches(store, team, opponent)
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
