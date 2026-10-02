#!/bin/bash
# Starts the WhatsApp collector and the daily job; if either stops, the
# container exits so the hosting platform restarts it.
set -uo pipefail

node --disable-warning=ExperimentalWarning collector/index.js &

# RUN_ON_START=dry -> preview a run in the logs right away; =real -> do a real run now.
python -m wa_crm serve ${RUN_ON_START:+--run-now "$RUN_ON_START"} &

wait -n
echo "A process exited; stopping container so it restarts." >&2
exit 1
