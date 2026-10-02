# The daily job / API (Python). The WhatsApp collector runs in its own container
# (collector/Dockerfile); both share the /data volume.
FROM python:3.12-slim-bookworm
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY wa_crm wa_crm
COPY scripts/start_cloud.sh scripts/

# Everything that must survive restarts (WhatsApp sessions, messages, state)
# lives in /data. Mount a persistent volume there.
ENV DATA_DIR=/data \
    WA_CRM_SOURCE=cloud \
    WA_CRM_CLOUD_DB_PATH=/data/messages.db \
    WA_CRM_STATE_PATH=/data/state.db \
    WA_CRM_CRM_CSV_PATH=/data/contacts.csv \
    PYTHONUNBUFFERED=1

CMD ["bash", "scripts/start_cloud.sh"]
