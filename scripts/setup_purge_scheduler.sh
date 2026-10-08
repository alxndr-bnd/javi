#!/usr/bin/env bash
# SERBITO-467: one-time setup of the daily recipient-data purge (Cloud Scheduler -> Cloud Run).
# Creates or updates the Cloud Scheduler job that POSTs /tasks/purge-recipient-pii/ every day.
# The app checks the shared secret TASKS_SECRET in the X-Tasks-Secret header, the same way as the
# Cloud Tasks callbacks. The script reads the secret from Secret Manager and never prints it.
#
# Run by hand once (needs roles/cloudscheduler.admin and access to the javi-tasks-secret secret):
#   bash scripts/setup_purge_scheduler.sh
# Check a run:  gcloud scheduler jobs run javi-purge-recipient-pii --location=europe-west1
# Details: SETUP_CICD.md, section 10.
set -euo pipefail

PROJECT="${PROJECT:-serbito}"
LOCATION="${LOCATION:-europe-west1}"
JOB="${JOB:-javi-purge-recipient-pii}"
URL="${URL:-https://javi.serbito.rs/tasks/purge-recipient-pii/}"
SCHEDULE="${SCHEDULE:-30 2 * * *}" # 02:30 Europe/Belgrade, low traffic
TIME_ZONE="${TIME_ZONE:-Europe/Belgrade}"

secret="$(gcloud secrets versions access latest --secret=javi-tasks-secret --project="$PROJECT")"
if [ -z "$secret" ]; then
  echo "javi-tasks-secret is empty. Stop." >&2
  exit 1
fi

if gcloud scheduler jobs describe "$JOB" --location="$LOCATION" --project="$PROJECT" >/dev/null 2>&1; then
  action=update
  headers_flag=--update-headers
else
  action=create
  headers_flag=--headers
fi

gcloud scheduler jobs "$action" http "$JOB" \
  --project="$PROJECT" \
  --location="$LOCATION" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIME_ZONE" \
  --uri="$URL" \
  --http-method=POST \
  "$headers_flag=X-Tasks-Secret=$secret" \
  --attempt-deadline=120s \
  --max-retry-attempts=3 \
  --description="SERBITO-467: erase recipient data past RECIPIENT_PII_RETENTION_DAYS" \
  --format='value(name)'
echo "Cloud Scheduler job $JOB: ${action}d ($SCHEDULE $TIME_ZONE -> $URL)."
