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
    col = _get_db().collection("match_log").document(fixture_id).collection("events")
    event_with_ts = {**event, "recorded_at": datetime.now(timezone.utc)}
    _, ref = col.add(event_with_ts)
    return ref.id


def get_match_history(fixture_id: str) -> list[dict]:
    """Return all events logged so far for this fixture, oldest first."""
    col = _get_db().collection("match_log").document(fixture_id).collection("events")
    docs = col.order_by("recorded_at").stream()
    return [doc.to_dict() for doc in docs]


# ---------------------------------------------------------------------------
# Insights — AI output per fixture
# ---------------------------------------------------------------------------

def write_insight(fixture_id: str, insight: dict) -> str:
    """Persist a ranked AI insight. Returns the document ID."""
    col = _get_db().collection("insights").document(fixture_id).collection("items")
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
        col.where("status", "==", "pending")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]


def get_all_pending_insights() -> list[dict]:
    """Return pending insights across all fixtures for the dashboard."""
    db = _get_db()

    # Prefer collection group query (faster) when the index exists.
    try:
        docs = (
            db.collection_group("items")
            .where("status", "==", "pending")
            .stream()
        )
        return [{"id": doc.id, **doc.to_dict()} for doc in docs]
    except Exception:
        # Fallback path for projects that do not yet have the required
        # collection-group index.
        results: list[dict] = []
        fixture_docs = db.collection("insights").stream()
        for fixture_doc in fixture_docs:
            item_docs = (
                db.collection("insights")
                .document(fixture_doc.id)
                .collection("items")
                .where("status", "==", "pending")
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .stream()
            )
            for doc in item_docs:
                payload = doc.to_dict()
                if "fixture_id" not in payload:
                    payload["fixture_id"] = fixture_doc.id
                results.append({"id": doc.id, **payload})

        return results


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
