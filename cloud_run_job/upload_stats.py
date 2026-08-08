"""
Cloud Run Job — runs once before a match to upload pre-match stats to GCS.
Replaces the FootballEdit integration for the POC.

Usage:
    python main.py --fixture-id arsenal-vs-chelsea-2025-08-02 --stats-file stats.json
"""

import argparse
import json
import sys

from google.cloud import storage

import os

_GCS_BUCKET = os.environ.get("GCS_BUCKET", "football-poc-stats-avid")


def upload(fixture_id: str, stats_path: str) -> None:
    with open(stats_path, "r") as f:
        stats = json.load(f)

    client = storage.Client()
    bucket = client.bucket(_GCS_BUCKET)
    blob = bucket.blob(f"pre-match/{fixture_id}.json")
    blob.upload_from_string(json.dumps(stats, indent=2), content_type="application/json")
    print(f"Uploaded pre-match stats to gs://{_GCS_BUCKET}/pre-match/{fixture_id}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload pre-match stats to GCS")
    parser.add_argument("--fixture-id", required=True, help="Unique fixture identifier, e.g. arsenal-vs-chelsea-2025-08-02")
    parser.add_argument("--stats-file", required=True, help="Path to the pre-match stats JSON file")
    args = parser.parse_args()

    try:
        upload(args.fixture_id, args.stats_file)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
