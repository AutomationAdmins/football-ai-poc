import json
import os

from google.cloud import storage

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "football-poc-stats-avid")
_client = None


def _get_client() -> storage.Client:
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def get_prematch_stats(fixture_id: str) -> dict:
    """Download and return pre-match stats JSON for a fixture from GCS."""
    bucket = _get_client().bucket(_GCS_BUCKET)
    blob = bucket.blob(f"pre-match/{fixture_id}.json")
    data = blob.download_as_text()
    return json.loads(data)


def upload_prematch_stats(fixture_id: str, stats: dict) -> None:
    """Upload a pre-match stats dict to GCS (used by the Cloud Run Job)."""
    bucket = _get_client().bucket(_GCS_BUCKET)
    blob = bucket.blob(f"pre-match/{fixture_id}.json")
    blob.upload_from_string(json.dumps(stats, indent=2), content_type="application/json")
