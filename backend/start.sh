#!/usr/bin/env bash
# Persistent launcher for the Hermes Messenger backend.
set -e
cd /root/hermes-messenger/backend
export MESSENGER_BOTS="$(cat /root/hermes-messenger/backend/bots.json)"
export HERMES_BIN=/root/.local/bin/hermes
export MESSENGER_DB=/root/hermes-messenger/backend/messenger.db
exec /usr/local/lib/hermes-agent/venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000
