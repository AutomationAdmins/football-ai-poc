import json
import os
from functools import lru_cache

from google.cloud import storage

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "football-poc-stats-avid")
_LOCAL_STATS_FILE = os.path.join(os.path.dirname(__file__), "historical_stats.json")
_client = None


def _local_mode() -> bool:
    return os.environ.get("DISABLE_FIRESTORE", "").strip().lower() in {"1", "true", "yes", "on"}


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


@lru_cache(maxsize=10)
def get_prematch_stats(fixture_id: str) -> dict:
    """Download and return pre-match stats JSON for a fixture from GCS.
    Falls back to local historical_stats.json when DISABLE_FIRESTORE=1."""
    if _local_mode():
        with open(_LOCAL_STATS_FILE, "r") as f:
            return json.load(f)
    bucket = _get_client().bucket(_GCS_BUCKET)
    blob = bucket.blob(f"pre-match/{fixture_id}.json")
    data = blob.download_as_text()
    return json.loads(data)


def upload_prematch_stats(fixture_id: str, stats: dict) -> None:
    """Upload a pre-match stats dict to GCS (used by the Cloud Run Job)."""
    bucket = _get_client().bucket(_GCS_BUCKET)
    blob = bucket.blob(f"pre-match/{fixture_id}.json")
    blob.upload_from_string(json.dumps(stats, indent=2), content_type="application/json")
