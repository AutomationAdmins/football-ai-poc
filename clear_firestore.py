import os
os.environ["GRPC_DNS_RESOLVER"] = "native"
from google.cloud import firestore

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

if __name__ == "__main__":
    db = firestore.Client(project=_PROJECT)
    
    print("Clearing 'insights' collection...")
    delete_collection(db.collection("insights"), 50)
    
    print("Clearing 'match_log' collection...")
    delete_collection(db.collection("match_log"), 50)
    
    print("Clearing 'decisions' collection...")
    delete_collection(db.collection("decisions"), 50)
    
    print("Done! Database is clean.")
