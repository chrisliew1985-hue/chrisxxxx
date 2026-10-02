# One container: the always-on WhatsApp collector (Node) + the daily
# Claude -> Calendar -> CRM job (Python).

FROM node:22-bookworm-slim AS collector
WORKDIR /app/collector
COPY collector/package.json collector/package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=collector /usr/local/bin/node /usr/local/bin/node
COPY --from=collector /app/collector/node_modules collector/node_modules

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY collector/package.json collector/index.js collector/
COPY wa_crm wa_crm
COPY scripts/start_cloud.sh scripts/

# Everything that must survive restarts (WhatsApp sessions, messages, state)
# lives in /data. Mount a persistent volume there (Railway: add a Volume at /data).
ENV DATA_DIR=/data \
    WA_CRM_SOURCE=cloud \
    WA_CRM_CLOUD_DB_PATH=/data/messages.db \
    WA_CRM_STATE_PATH=/data/state.db \
    WA_CRM_CRM_CSV_PATH=/data/contacts.csv \
    PYTHONUNBUFFERED=1

CMD ["bash", "scripts/start_cloud.sh"]
