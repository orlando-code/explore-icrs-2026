FROM python:3.12-slim

WORKDIR /app
COPY offset_api.py .
# Verified emails are gitignored; deploy script copies export output here when present.
COPY data/contacts.json data/contacts.json
COPY data/delegate_ids.csv data/delegate_ids.csv

ENV OFFSET_DB_PATH=/data/offsets.db
ENV CONTACTS_PATH=/app/data/contacts.json
ENV DELEGATE_IDS_PATH=/app/data/delegate_ids.csv
ENV PORT=8080
ENV HOST=0.0.0.0

VOLUME /data
EXPOSE 8080

CMD ["python", "offset_api.py"]
