FROM python:3.12-slim

WORKDIR /app
COPY offset_api.py .

ENV OFFSET_DB_PATH=/data/offsets.db
ENV PORT=8080
ENV HOST=0.0.0.0

VOLUME /data
EXPOSE 8080

CMD ["python", "offset_api.py"]
