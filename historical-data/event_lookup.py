#!/usr/bin/env python3
"""
Event Context Retrieval Script
-------------------------------
Given a match event (goal, assist, card, etc.), retrieves all relevant contextual
data from the CSV files in this workspace: player stats, H2H records, fixture
history, match details, and fixture leaders.

Usage:
    # As a CLI tool (JSON input):
    echo '{"event": "GOAL", "player": "Erling Haaland", "team": "Manchester City", "opponent": "Manchester United", "date": "2026-09-13", "minutes": 8}' | python event_lookup.py

    # As a Python module:
    from event_lookup import enrich_event
    result = enrich_event({"event": "GOAL", "player": "Erling Haaland", ...})
"""

import json
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# Base directory is where this script lives
BASE_DIR = Path(__file__).resolve().parent


# ─── Utilities ────────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize a player/team name for matching: lowercase, strip accents, strip whitespace."""
    if not name:
        return ""
    # Decompose unicode, strip combining marks (accents)
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
    """Derive football season identifiers from a date.
    Returns dict with multiple formats for matching:
        - 'full': '2026-2027'
        - 'start_year': '2026'
        - 'hyphenated': '2026-2027'
    """
    iso = parse_date(date_str)
    if not iso:
        return {}
    dt = datetime.strptime(iso, "%Y-%m-%d")
    # Season starts in August
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


# Common team name aliases for folder matching
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


# ─── Data Loading ─────────────────────────────────────────────────────────────

class DataStore:
    """Loads and caches all CSV files from the workspace, auto-discovering folders."""

    def __init__(self, base_dir: Path = BASE_DIR):
        self.base_dir = base_dir
        self._cache: dict[str, pd.DataFrame] = {}
        self._discover_files()

    def _discover_files(self):
        """Scan all subdirectories for CSV files and load them."""
        for csv_path in self.base_dir.rglob("*.csv"):
            rel_path = csv_path.relative_to(self.base_dir)
            key = str(rel_path)
            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig", on_bad_lines="skip")
                # Strip whitespace from column names
                df.columns = df.columns.str.strip()
                self._cache[key] = df
            except Exception:
                continue

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """Get a DataFrame by its relative path key."""
        return self._cache.get(key)

    def find_files(self, pattern: str) -> list[tuple[str, pd.DataFrame]]:
        """Find all loaded files whose key contains the given pattern (case-insensitive)."""
        pattern_lower = pattern.lower()
        return [(k, v) for k, v in self._cache.items() if pattern_lower in k.lower()]

    def find_player_files(self, player_name: str) -> list[tuple[str, pd.DataFrame]]:
        """Find CSV files in a folder matching the player name."""
        slug = team_slug(player_name).replace("_", " ")
        results = []
        for key, df in self._cache.items():
            folder = Path(key).parts[0] if Path(key).parts else ""
            if name_matches(folder, player_name):
                results.append((key, df))
            # Also check if the DataFrame has a 'player name' column with matching entries
            elif "player name" in [normalize_name(c) for c in df.columns]:
                col = next(c for c in df.columns if normalize_name(c) == "player name")
                if df[col].astype(str).apply(normalize_name).eq(normalize_name(player_name)).any():
                    results.append((key, df))
        return results

    def find_team_files(self, team_name: str) -> list[tuple[str, pd.DataFrame]]:
        """Find CSV files in a folder matching the team name."""
        results = []
        for key, df in self._cache.items():
            folder = Path(key).parts[0] if Path(key).parts else ""
            if team_name_matches(folder, team_name):
                results.append((key, df))
        return results


# ─── Lookup Functions ─────────────────────────────────────────────────────────

def lookup_match_details(store: DataStore, date: str, team: str, opponent: str) -> Optional[dict]:
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


def lookup_player_goal_log(store: DataStore, player: str, date: str, minute: Optional[int] = None) -> Optional[dict]:
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
                # Handle "90+5" style minutes
                try:
                    base_min = int(str(row_min).split("+")[0])
                except (ValueError, TypeError):
                    base_min = None
                if base_min is not None and base_min != minute and row_min != str(minute):
                    continue
            return row.dropna().to_dict()
    return None


def lookup_player_assist_log(store: DataStore, player: str, date: str, minute: Optional[int] = None) -> Optional[dict]:
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


def lookup_player_season_stats(store: DataStore, player: str, date: str) -> Optional[dict]:
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


def lookup_player_club_summary(store: DataStore, player: str, date: str) -> Optional[dict]:
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


def lookup_player_vs_opponent(store: DataStore, player: str, team: str, opponent: str) -> Optional[dict]:
    """Get the player's head-to-head record vs the opponent."""
    # Look in team folder for *_players_vs_*.csv
    team_files = store.find_team_files(team)
    for key, df in team_files:
        if "players_vs" not in key.lower():
            continue
        # Check if opponent name is in the filename
        opp_slug = team_slug(opponent)
        if opp_slug.replace("_", "") not in key.lower().replace("_", "").replace(" ", ""):
            # Try partial match
            opp_parts = normalize_name(opponent).split()
            if not any(part in key.lower() for part in opp_parts):
                continue
        # Find the player row
        player_col = "Player" if "Player" in df.columns else "player"
        if player_col not in df.columns:
            continue
        for _, row in df.iterrows():
            if name_matches(str(row.get(player_col, "")), player):
                return row.dropna().to_dict()
    return None


def lookup_team_vs_opponent(store: DataStore, team: str, opponent: str) -> Optional[dict]:
    """Get the team's overall record vs the opponent."""
    team_files = store.find_team_files(team)
    for key, df in team_files:
        if "vs_opponents_records" not in key.lower():
            continue
        # Find opponent row
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


def lookup_fixture_leaders(store: DataStore, team: str) -> dict[str, list[dict]]:
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


def lookup_team_league_history(store: DataStore, team: str, date: str) -> Optional[dict]:
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


def lookup_derby_events(store: DataStore, date: str, player: Optional[str] = None) -> list[dict]:
    """Get all derby events for a given date (and optionally player)."""
    iso_date = parse_date(date)
    events_files = store.find_files("derby_events.csv")
    results = []
    for key, df in events_files:
        if "match_id" not in df.columns:
            continue
        for _, row in df.iterrows():
            match_id = str(row.get("match_id", ""))
            # match_id format: YYYY-MM-DD_team1_vs_team2
            if iso_date and match_id.startswith(iso_date):
                if player and "player_name" in df.columns:
                    if not name_matches(str(row.get("player_name", "")), player):
                        continue
                results.append(row.dropna().to_dict())
    return results


# ─── Main Enrichment Function ────────────────────────────────────────────────

def enrich_event(event: dict[str, Any], store: Optional[DataStore] = None) -> dict[str, Any]:
    """
    Given a match event dict, retrieve all relevant contextual data.

    Expected event keys:
        - event: str (GOAL, ASSIST, CARD, etc.)
        - player: str
        - team: str
        - opponent: str
        - date: str (any common format)
        - minutes: int (optional)
        - league: str (optional)
        - score: str (optional)
        - x, y, xG, pass_accuracy: float (optional, passed through)

    Returns a dict with the original event plus enriched data sections.
    """
    if store is None:
        store = DataStore()

    player = event.get("player", "")
    team = event.get("team", "")
    opponent = event.get("opponent", "")
    date = event.get("date", "")
    minute = event.get("minutes")
    event_type = event.get("event", "").upper()

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
    }

    # Match details
    result["match_details"] = lookup_match_details(store, date, team, opponent)

    # Player event logs
    if event_type == "GOAL":
        result["player_goal_log_entry"] = lookup_player_goal_log(store, player, date, minute)
    elif event_type == "ASSIST":
        result["player_assist_log_entry"] = lookup_player_assist_log(store, player, date, minute)
    else:
        # Try both for generic events
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

    # Related derby events for same match
    result["related_derby_events"] = lookup_derby_events(store, date, player=None)

    # Remove None values from top-level for cleaner output
    result = {k: v for k, v in result.items() if v is not None and v != [] and v != {}}

    return result


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    """Read event JSON from stdin or first CLI argument, print enriched result."""
    if len(sys.argv) > 1:
        # Read from file argument
        with open(sys.argv[1], "r") as f:
            event = json.load(f)
    else:
        # Read from stdin
        raw = sys.stdin.read().strip()
        if not raw:
            print("Usage: echo '{\"event\": \"GOAL\", ...}' | python event_lookup.py", file=sys.stderr)
            sys.exit(1)
        event = json.loads(raw)

    store = DataStore()
    result = enrich_event(event, store)

    # Output as formatted JSON
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
