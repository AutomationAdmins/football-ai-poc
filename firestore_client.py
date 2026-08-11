import os
import uuid
from datetime import datetime, timezone
import logging

from google.cloud import firestore

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")
_db = None
logger = logging.getLogger(__name__)

# In-memory stores used when DISABLE_FIRESTORE=1
_mem_insights: list[dict] = []
_mem_match_log: list[dict] = []


def _firestore_disabled() -> bool:
    return os.environ.get("DISABLE_FIRESTORE", "").strip().lower() in {"1", "true", "yes", "on"}


def _get_db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=_PROJECT)
    return _db


# ---------------------------------------------------------------------------
# Match log (Layer 2) — in-match event history per fixture
# ---------------------------------------------------------------------------

def append_match_event(fixture_id: str, event: dict) -> str:
    """Append a processed event to the match log. Returns the new document ID."""
    if _firestore_disabled():
        doc_id = str(uuid.uuid4())
        _mem_match_log.append({"id": doc_id, "fixture_id": fixture_id, **event, "recorded_at": datetime.now(timezone.utc)})
        return doc_id
    db = _get_db()
    db.collection("match_log").document(fixture_id).set({"fixture_id": fixture_id}, merge=True)
    col = db.collection("match_log").document(fixture_id).collection("events")
    event_with_ts = {**event, "recorded_at": datetime.now(timezone.utc)}
    _, ref = col.add(event_with_ts)
    return ref.id


def get_match_history(fixture_id: str, limit: int = 10) -> list[dict]:
    """Return recent events logged so far for this fixture, oldest first."""
    if _firestore_disabled():
        events = [e for e in _mem_match_log if e.get("fixture_id") == fixture_id]
        return events[-limit:]
    col = _get_db().collection("match_log").document(fixture_id).collection("events")
    # Fetch the most recent 'limit' events
    docs = col.order_by("recorded_at", direction=firestore.Query.DESCENDING).limit(limit).stream()
    # Reverse to keep chronological order (oldest to newest)
    events = [doc.to_dict() for doc in docs]
    events.reverse()
    return events


# ---------------------------------------------------------------------------
# Insights — AI output per fixture
# ---------------------------------------------------------------------------

def write_insight(fixture_id: str, insight: dict) -> str:
    """Persist a ranked AI insight. Returns the document ID."""
    # Sanitize unicode characters that render as garbled text in browsers
    def _s(text):
        if not isinstance(text, str):
            return text
        return (text
            .replace('\u2014', ' - ').replace('\u2013', ' - ')
            .replace('\u2019', "'").replace('\u2018', "'")
            .replace('\u201c', '"').replace('\u201d', '"')
            .replace('\u2026', '...')
        )

    clean = {**insight}
    if 'lead_story' in clean:
        clean['lead_story'] = _s(clean['lead_story'])
    if 'insights' in clean and isinstance(clean['insights'], list):
        clean['insights'] = [{**i, 'line': _s(i.get('line', ''))} for i in clean['insights']]

    if _firestore_disabled():
        doc_id = str(uuid.uuid4())
        _mem_insights.append({"id": doc_id, "fixture_id": fixture_id, "status": "pending", "created_at": datetime.now(timezone.utc), **clean})
        return doc_id
    db = _get_db()
    db.collection("insights").document(fixture_id).set({"fixture_id": fixture_id, "updated_at": datetime.now(timezone.utc)}, merge=True)
    col = db.collection("insights").document(fixture_id).collection("items")
    payload = {
        **clean,
        "fixture_id": fixture_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    _, ref = col.add(payload)
    return ref.id


def get_pending_insights(fixture_id: str) -> list[dict]:
    """Return all pending insights for a fixture, newest first."""
    if _firestore_disabled():
        results = [i for i in _mem_insights if i.get("fixture_id") == fixture_id and i.get("status") == "pending"]
        return sorted(results, key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    try:
        col = _get_db().collection("insights").document(fixture_id).collection("items")
        docs = (
            col.where(filter=firestore.FieldFilter("status", "==", "pending"))
            .stream()
        )
        results = [{"id": doc.id, **doc.to_dict()} for doc in docs]
        results.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return results
    except Exception as exc:
        logger.warning("Firestore unavailable for get_pending_insights(%s): %s", fixture_id, exc)
        return []


def get_all_pending_insights() -> list[dict]:
    """Return pending insights across all fixtures for the dashboard."""
    if _firestore_disabled():
        results = [i for i in _mem_insights if i.get("status") == "pending"]
        return sorted(results, key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    try:
        db = _get_db()
        results: list[dict] = []

        # Use a Collection Group query on 'items' subcollections
        item_docs = db.collection_group("items").stream()

        for doc in item_docs:
            # Only include items under insights/ (not training_data/)
            if "training_data" in doc.reference.path:
                continue
            payload = doc.to_dict()
            if payload.get("status") == "pending":
                results.append({"id": doc.id, **payload})

        results.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return results
    except Exception as exc:
        logger.warning("Firestore unavailable for get_all_pending_insights: %s", exc)
        return []


def get_used_insight_lines(fixture_id: str) -> set[str]:
    # Note: for local mode this returns set() (handled below)
    """
    Return all insight lines already shown for this fixture.
    Used for anti-repetition filtering.
    """
    if _firestore_disabled():
        used = set()
        for item in _mem_insights:
            if item.get("fixture_id") == fixture_id:
                for ins in item.get("insights", []):
                    if ins.get("line"):
                        used.add(ins["line"].strip())
        return used

    col = _get_db().collection("insights").document(fixture_id).collection("items")
    docs = col.stream()
    
    used_lines = set()
    for doc in docs:
        data = doc.to_dict()
        insights = data.get("insights", [])
        for insight in insights:
            line = insight.get("line")
            if line:
                used_lines.add(line.strip())
    
    return used_lines


