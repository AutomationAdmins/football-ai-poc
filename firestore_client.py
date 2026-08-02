import os
from datetime import datetime, timezone

from google.cloud import firestore

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")
_db = None


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
    db = _get_db()
    db.collection("match_log").document(fixture_id).set({"fixture_id": fixture_id}, merge=True)
    col = db.collection("match_log").document(fixture_id).collection("events")
    event_with_ts = {**event, "recorded_at": datetime.now(timezone.utc)}
    _, ref = col.add(event_with_ts)
    return ref.id


def get_match_history(fixture_id: str, limit: int = 10) -> list[dict]:
    """Return recent events logged so far for this fixture, oldest first."""
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
    db = _get_db()
    db.collection("insights").document(fixture_id).set({"fixture_id": fixture_id, "updated_at": datetime.now(timezone.utc)}, merge=True)
    col = db.collection("insights").document(fixture_id).collection("items")
    payload = {
        **insight,
        "fixture_id": fixture_id,
        "status": "pending",  # pending | approved | rejected
        "created_at": datetime.now(timezone.utc),
    }
    _, ref = col.add(payload)
    return ref.id


def get_pending_insights(fixture_id: str) -> list[dict]:
    """Return all pending insights for a fixture, newest first."""
    col = _get_db().collection("insights").document(fixture_id).collection("items")
    docs = (
        col.where(filter=firestore.FieldFilter("status", "==", "pending"))
        .stream()
    )
    results = [{"id": doc.id, **doc.to_dict()} for doc in docs]
    results.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results


def get_all_pending_insights() -> list[dict]:
    """Return pending insights across all fixtures for the dashboard."""
    db = _get_db()
    results: list[dict] = []
    
    # Use a Collection Group query without filter to avoid index requirement
    item_docs = db.collection_group("items").stream()
    
    for doc in item_docs:
        payload = doc.to_dict()
        if payload.get("status") == "pending":
            results.append({"id": doc.id, **payload})

    results.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results


def get_used_insight_lines(fixture_id: str) -> set[str]:
    """
    Return all insight lines already shown for this fixture.
    Used for anti-repetition filtering.
    """
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
# Decisions — statistician approve / reject
# ---------------------------------------------------------------------------

def record_decision(fixture_id: str, insight_id: str, approved: bool) -> None:
    """Record a statistician decision against an insight."""
    db = _get_db()
    # Update the insight status
    db.collection("insights").document(fixture_id).collection("items").document(insight_id).update({
        "status": "approved" if approved else "rejected",
        "decided_at": datetime.now(timezone.utc),
    })
    # Write a top-level decision record for audit/analytics
    db.collection("decisions").add({
        "insight_id": insight_id,
        "fixture_id": fixture_id,
        "approved": approved,
        "decided_at": datetime.now(timezone.utc),
    })
