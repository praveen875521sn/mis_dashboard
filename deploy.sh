#!/bin/bash
# deploy.sh — Deploy ECP Dashboard to Cloud Run with large-file settings
#
# Run: bash deploy.sh
#
# KEY FLAGS for 300MB+ files / 3GB total data:
#   --memory 4Gi          : 3GB in-memory data + rebuild overhead needs 4GB
#   --timeout 3600        : Cloud Run HTTP timeout — 300MB upload over office wifi
#                           can take 30-60 min. Set to max (3600s = 1 hour).
#   --concurrency 10      : 1 gunicorn worker × 8 threads; limit Cloud Run to 10
#                           concurrent requests per instance (avoid RAM spikes)
#   --min-instances 1     : Keep 1 instance warm so in-memory data survives
#                           between requests (cold start = full rebuild)
#   --max-instances 1     : CRITICAL — multiple instances = each has own RAM copy
#                           of 3GB data. With 1 instance, uploads are safe.
#                           Increase only if you move to a DB-query model.

PROJECT="project-0915c8ee-16ec-42f4-8d3"
SERVICE="ecp-dashboard"
REGION="asia-south1"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"

set -e

echo "=== Building Docker image ==="
gcloud builds submit --tag "$IMAGE" --project "$PROJECT"

echo "=== Deploying to Cloud Run ==="
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --platform managed \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 10 \
  --min-instances 1 \
  --max-instances 1 \
  --set-env-vars "$(cat .env | grep -v '^#' | grep '=' | tr '\n' ','| sed 's/,$//')"

echo "=== Done ==="
gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format "value(status.url)"
