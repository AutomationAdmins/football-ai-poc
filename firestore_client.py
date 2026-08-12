import os
import uuid
import threading
import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional
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
        # Notify SSE stream that new data is available
        with _snapshot_lock:
            global _latest_snapshot
            _latest_snapshot = sorted(
                [i for i in _mem_insights if i.get("status") == "pending"],
                key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
        _snapshot_event.set()
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


def clear_mem_insights():
    """Clear in-memory insights store and notify SSE stream (local mode only)."""
    global _mem_insights, _latest_snapshot
    _mem_insights.clear()
    with _snapshot_lock:
        _latest_snapshot = []
    _snapshot_event.set()



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


# ---------------------------------------------------------------------------
# Real-time listener for SSE — replaces polling
# ---------------------------------------------------------------------------

# Shared state for the latest snapshot, protected by a threading.Event so
# SSE consumers can block until new data arrives.
_latest_snapshot: list[dict] = []
_snapshot_event = threading.Event()
_snapshot_lock = threading.Lock()
_listener_unsub: Optional[Callable] = None


def _on_snapshot(col_snapshot, changes, read_time):
    """Firestore on_snapshot callback — runs on a background thread."""
    results: list[dict] = []
    for doc in col_snapshot:
        if "training_data" in doc.reference.path:
            continue
        payload = doc.to_dict()
        if payload.get("status") == "pending":
            results.append({"id": doc.id, **payload})
    results.sort(
        key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    global _latest_snapshot
    with _snapshot_lock:
        _latest_snapshot = results
    _snapshot_event.set()


def start_insights_listener():
    """Start a Firestore on_snapshot listener for all pending insights.
    Safe to call multiple times — subsequent calls are no-ops."""
    global _listener_unsub
    if _listener_unsub is not None:
        return  # already listening
    if _firestore_disabled():
        logger.info("Firestore disabled — skipping real-time listener")
        return
    db = _get_db()
    query = db.collection_group("items")
    _listener_unsub = query.on_snapshot(_on_snapshot)
    logger.info("Firestore on_snapshot listener started for insights")


def stop_insights_listener():
    """Unsubscribe the real-time listener."""
    global _listener_unsub
    if _listener_unsub is not None:
        _listener_unsub.unsubscribe()
        _listener_unsub = None
        logger.info("Firestore on_snapshot listener stopped")


def wait_for_snapshot_update(timeout: float = 30.0) -> list[dict]:
    """Block until a new snapshot arrives (or timeout). Returns the latest data."""
    _snapshot_event.wait(timeout=timeout)
    _snapshot_event.clear()
    with _snapshot_lock:
        if _latest_snapshot:
            return list(_latest_snapshot)
    # Fallback for local mode if snapshot was never populated
    if _firestore_disabled():
        return sorted(
            [i for i in _mem_insights if i.get("status") == "pending"],
            key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    return []


def get_latest_snapshot() -> list[dict]:
    """Return the most recent snapshot without blocking."""
    with _snapshot_lock:
        return list(_latest_snapshot)
