#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT:=avid-invention-484506-g9}"
: "${SERVICE_NAME:=football-monitoring}"
: "${REGION:=us-central1}"
: "${SERVICE_ACCOUNT:=football-poc-sa@avid-invention-484506-g9.iam.gserviceaccount.com}"

gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${GCP_PROJECT}" \
  --region "${REGION}" \
  --service-account "${SERVICE_ACCOUNT}" \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT=${GCP_PROJECT}" \
  --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --memory=512Mi \
  --timeout=60

echo ""
echo "Monitoring deployed!"
echo "URL: $(gcloud run services describe ${SERVICE_NAME} --project ${GCP_PROJECT} --region ${REGION} --format='value(status.url)')"
