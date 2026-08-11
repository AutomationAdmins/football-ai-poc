import os
os.environ["GRPC_DNS_RESOLVER"] = "native"
from google.cloud import firestore
from datetime import datetime, timezone

_PROJECT = os.environ.get("GCP_PROJECT", "avid-invention-484506-g9")

def delete_collection(coll_ref, batch_size):
    docs = coll_ref.limit(batch_size).stream()
    deleted = 0

    for doc in docs:
        print(f"Deleting doc {doc.id} => {doc.reference.path}")
        # Delete subcollections if any (we know we have 'items' and 'events')
        delete_subcollections(doc.reference, batch_size)
        doc.reference.delete()
        deleted += 1

    if deleted >= batch_size:
        return delete_collection(coll_ref, batch_size)

def delete_subcollections(doc_ref, batch_size):
    for subcoll in doc_ref.collections():
        delete_collection(subcoll, batch_size)


def archive_insights(db):
    """
    Copy all insights into training_data/ collection before deleting.
    Each archive batch gets a timestamp ID so nothing is overwritten.
    """
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_ref = db.collection("training_data").document(batch_id)
    
    # Get all fixture docs under insights/
    fixture_docs = list(db.collection("insights").stream())
    
    if not fixture_docs:
        print("No insights to archive.")
        return 0
    
    archived_count = 0
    
    for fixture_doc in fixture_docs:
        fixture_id = fixture_doc.id
        
        # Get all insight items under this fixture
        items_ref = db.collection("insights").document(fixture_id).collection("items")
        items = list(items_ref.stream())
        
        for item in items:
            item_data = item.to_dict()
            item_data["_fixture_id"] = fixture_id
            item_data["_archived_at"] = datetime.now(timezone.utc).isoformat()
            item_data["_batch_id"] = batch_id
            item_data["status"] = "archived"
            
            # Store in training_data/{batch_id}/items/{original_id}
            archive_ref.collection("items").document(item.id).set(item_data)
            archived_count += 1
    
    # Store batch metadata
    archive_ref.set({
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "item_count": archived_count,
        "fixture_ids": [doc.id for doc in fixture_docs],
    })
    
    print(f"Archived {archived_count} insights to training_data/{batch_id}")
    return archived_count


def clear_all(db):
    """Archive insights then clear all collections."""
    archive_insights(db)
    
    print("\nClearing 'insights' collection...")
    delete_collection(db.collection("insights"), 50)
    
    print("Clearing 'match_log' collection...")
    delete_collection(db.collection("match_log"), 50)
    
    print("Done! Database is clean.")


if __name__ == "__main__":
    db = firestore.Client(project=_PROJECT)
    clear_all(db)
