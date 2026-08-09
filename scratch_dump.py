import json
from google.cloud import firestore

db = firestore.Client(project="avid-invention-484506-g9")
docs = db.collection("insights").order_by("timestamp").stream()
for doc in docs:
    data = doc.to_dict()
    print(f"EVENT: {data.get('event_type')} at {data.get('minute')}' - {data.get('score')}")
    print(f"LEAD STORY: {data.get('lead_story')}")
    print("INSIGHTS:")
    for ins in data.get('insights', []):
        print(f" - [{ins.get('category')}] {ins.get('line')}")
    print("-" * 40)
