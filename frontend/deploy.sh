#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT:=avid-invention-484506-g9}"
: "${SERVICE_NAME:=football-dashboard}"
: "${REGION:=us-central1}"
: "${BACKEND_API_URL:=https://football-poc-262513106870.us-central1.run.app}"
: "${SERVICE_ACCOUNT:=football-poc-sa@avid-invention-484506-g9.iam.gserviceaccount.com}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is required" >&2
  exit 1
fi

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${GCP_PROJECT}" \
  --region "${REGION}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --allow-unauthenticated \
  --set-env-vars "BACKEND_API_URL=${BACKEND_API_URL}"
