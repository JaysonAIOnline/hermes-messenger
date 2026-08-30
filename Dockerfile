FROM python:3.11-slim

WORKDIR /app

# System deps (none required beyond python). Hermes CLI is expected on the host;
# if you want bots inside the container, install Hermes here and mount its config.
RUN pip install --no-cache-dir fastapi uvicorn[standard] websockets

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ENV MESSENGER_DB=/data/messenger.db
RUN mkdir -p /data

EXPOSE 8000
CMD ["sh", "-c", "cd /app/backend && uvicorn server:app --host 0.0.0.0 --port 8000"]
