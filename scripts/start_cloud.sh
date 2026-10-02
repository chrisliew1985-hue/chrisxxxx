#!/bin/bash
# Starts the Python side. The WhatsApp collector is a separate container.
set -uo pipefail

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # API-key mode: this container runs Claude itself every day at WA_CRM_RUN_AT.
  # RUN_ON_START=dry -> preview a run in the logs right away; =real -> do a real run now.
  exec python -m wa_crm serve ${RUN_ON_START:+--run-now "$RUN_ON_START"}
else
  # No-key mode: a daily Claude Routine on your Claude plan calls this API.
  exec python -m wa_crm api --port 8080
fi
