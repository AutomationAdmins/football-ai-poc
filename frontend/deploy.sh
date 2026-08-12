#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT:=avid-invention-484506-g9}"
: "${SERVICE_NAME:=football-dashboard}"
: "${REGION:=us-central1}"
: "${BACKEND_SERVICE_NAME:=football-poc}"
: "${SERVICE_ACCOUNT:=football-poc-sa@avid-invention-484506-g9.iam.gserviceaccount.com}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is required" >&2
  exit 1
fi

if [[ -z "${BACKEND_API_URL:-}" ]]; then
  BACKEND_API_URL="$(gcloud run services describe "${BACKEND_SERVICE_NAME}" \
    --project "${GCP_PROJECT}" \
    --region "${REGION}" \
    --format='value(status.url)')"
fi

if [[ -z "${BACKEND_API_URL}" ]]; then
  echo "Could not resolve BACKEND_API_URL. Set it explicitly and retry." >&2
  exit 1
fi

echo "Deploying dashboard with BACKEND_API_URL=${BACKEND_API_URL}"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${GCP_PROJECT}" \
  --region "${REGION}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --allow-unauthenticated \
  --set-env-vars "BACKEND_API_URL=${BACKEND_API_URL}"
