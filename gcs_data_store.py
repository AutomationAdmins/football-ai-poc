"""
GCS-backed DataStore for loading CSV files from the premier league data prefix.

Falls back to the local historical-data/ folder when DISABLE_FIRESTORE=1.
"""

import io
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
from google.cloud import storage

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "football-poc-stats-avid")
_GCS_PREFIX = os.environ.get("GCS_DATA_PREFIX", "premier leaguge data")
_LOCAL_DATA_DIR = Path(__file__).resolve().parent / "historical-data"


def _local_mode() -> bool:
    return os.environ.get("DISABLE_FIRESTORE", "").strip().lower() in {"1", "true", "yes", "on"}


class GCSDataStore:
    """Loads and caches CSV files from GCS (or local fallback), matching the DataStore interface."""

    def __init__(self):
        self._cache: dict[str, pd.DataFrame] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        if _local_mode():
            self._load_local()
        else:
            self._load_gcs()
        self._loaded = True

    def _load_local(self):
        """Load CSVs from the local historical-data/ directory."""
        if not _LOCAL_DATA_DIR.exists():
            return
        for csv_path in _LOCAL_DATA_DIR.rglob("*.csv"):
            rel_path = csv_path.relative_to(_LOCAL_DATA_DIR)
            key = str(rel_path)
            try:
                df = pd.read_csv(csv_path, encoding="utf-8-sig", on_bad_lines="skip")
                df.columns = df.columns.str.strip()
                self._cache[key] = df
            except Exception:
                continue

    def _load_gcs(self):
        """Download all CSVs under the GCS prefix into memory."""
        client = storage.Client()
        bucket = client.bucket(_GCS_BUCKET)
        prefix = _GCS_PREFIX.strip("/") + "/"

        blobs = bucket.list_blobs(prefix=prefix)
        for blob in blobs:
            if not blob.name.endswith(".csv"):
                continue
            # Strip the prefix to get relative key (e.g. "Derby/derby_events.csv")
            rel_key = blob.name[len(prefix):]
            if not rel_key:
                continue
            try:
                csv_bytes = blob.download_as_bytes()
                df = pd.read_csv(
                    io.BytesIO(csv_bytes), encoding="utf-8-sig", on_bad_lines="skip"
                )
                df.columns = df.columns.str.strip()
                self._cache[rel_key] = df
            except Exception:
                continue

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """Get a DataFrame by its relative path key."""
        self._ensure_loaded()
        return self._cache.get(key)

    def find_files(self, pattern: str) -> list[tuple[str, pd.DataFrame]]:
        """Find all loaded files whose key contains the given pattern (case-insensitive)."""
        self._ensure_loaded()
        pattern_lower = pattern.lower()
        return [(k, v) for k, v in self._cache.items() if pattern_lower in k.lower()]

    def find_player_files(self, player_name: str) -> list[tuple[str, pd.DataFrame]]:
        """Find CSV files in a folder matching the player name."""
        self._ensure_loaded()
        from event_lookup import normalize_name, name_matches

        results = []
        for key, df in self._cache.items():
            folder = Path(key).parts[0] if Path(key).parts else ""
            if name_matches(folder, player_name):
                results.append((key, df))
            elif "player name" in [normalize_name(c) for c in df.columns]:
                col = next(c for c in df.columns if normalize_name(c) == "player name")
                if df[col].astype(str).apply(normalize_name).eq(normalize_name(player_name)).any():
                    results.append((key, df))
        return results

    def find_team_files(self, team_name: str) -> list[tuple[str, pd.DataFrame]]:
        """Find CSV files in a folder matching the team name."""
        self._ensure_loaded()
        from event_lookup import team_name_matches

        results = []
        for key, df in self._cache.items():
            folder = Path(key).parts[0] if Path(key).parts else ""
            if team_name_matches(folder, team_name):
                results.append((key, df))
        return results


# Module-level singleton (lazy-loaded)
_store: Optional[GCSDataStore] = None


def get_data_store() -> GCSDataStore:
    """Return the singleton GCSDataStore instance."""
    global _store
    if _store is None:
        _store = GCSDataStore()
    return _store


def reset_data_store():
    """Reset the singleton so next access reloads all CSVs from source."""
    global _store
    _store = None
