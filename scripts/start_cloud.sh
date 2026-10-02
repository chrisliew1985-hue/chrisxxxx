#!/bin/bash
# Starts the WhatsApp collector and the daily job; if either stops, the
# container exits so the hosting platform restarts it.
set -uo pipefail

node --disable-warning=ExperimentalWarning collector/index.js &

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # API-key mode: this container runs Claude itself every day at WA_CRM_RUN_AT.
  # RUN_ON_START=dry -> preview a run in the logs right away; =real -> do a real run now.
  python -m wa_crm serve ${RUN_ON_START:+--run-now "$RUN_ON_START"} &
else
  # No-key mode: a daily Claude Routine on your Claude plan calls this API.
  python -m wa_crm api --port 8080 &
fi

wait -n
echo "A process exited; stopping container so it restarts." >&2
exit 1
