#!/bin/bash
# Deployment script for backend improvements
# Run this after testing locally

set -e

PROJECT_ID="avid-invention-484506-g9"
REGION="us-central1"
SERVICE_NAME="football-poc"

echo "============================================================"
echo "DEPLOYING BACKEND IMPROVEMENTS TO CLOUD RUN"
echo "============================================================"
echo ""

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ ERROR: Must run from football-ai-poc directory"
    exit 1
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  WARNING: Virtual environment not activated"
    echo "   Activating now..."
    source .venv/bin/activate
fi

# Run tests first
# echo "1️⃣  Running tests..."
# python test_improvements.py
# if [ $? -ne 0 ]; then
#     echo "❌ Tests failed - aborting deployment"
#     exit 1
# fi
# echo "✅ Tests passed"
# echo ""

# Check for required files
echo "2️⃣  Checking deployment files..."
REQUIRED_FILES=(
    "app.py"
    "match_state_tracker.py"
    "firestore_client.py"
    "prompt_builder.py"
    "editorial_context.py"
    "sports_data.py"
    "ai_engine.py"
    "event_processor.py"
    "gcs_client.py"
    "gcs_data_store.py"
    "event_lookup.py"
    "requirements.txt"
    "Dockerfile"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ Missing required file: $file"
        exit 1
    fi
done
echo "✅ All required files present"
echo ""

# Build and deploy to Cloud Run
echo "3️⃣  Building and deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --source . \
    --project=$PROJECT_ID \
    --region=$REGION \
    --platform=managed \
    --allow-unauthenticated \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=football-poc-stats-avid,FIXTURE_ID=arsenal-vs-chelsea-2025-08-02" \
    --memory=1Gi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=10

if [ $? -ne 0 ]; then
    echo "❌ Deployment failed"
    exit 1
fi

echo ""
echo "============================================================"
echo "✅ DEPLOYMENT SUCCESSFUL"
echo "============================================================"
echo ""
echo "Service URL: https://$SERVICE_NAME-262513106870.$REGION.run.app"
echo ""
echo "Next steps:"
echo "1. Test health endpoint:"
echo "   curl https://$SERVICE_NAME-262513106870.$REGION.run.app/health"
echo ""
echo "2. Run simulator to test end-to-end:"
echo "   python simulate_match.py --fixture-id arsenal-vs-chelsea-2025-08-02 --delay 2"
echo ""
echo "3. Check dashboard:"
echo "   https://football-dashboard-262513106870.$REGION.run.app"
echo ""
echo "4. Verify improvements:"
echo "   - No repeated insights across events"
echo "   - Saka's 3rd goal shows HAT-TRICK"
echo "   - xG data appears in insights"
echo "   - Build-up players credited"
echo ""
