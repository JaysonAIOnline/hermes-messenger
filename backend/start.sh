#!/bin/bash
set -e
export HERMES_BIN=/root/.local/bin/hermes
export MESSENGER_DB=/root/hermes-messenger/backend/messenger.db
export MESSENGER_BOTS='[{"id": "hermes", "name": "Hermes", "profile": ""}, {"id": "analyst", "name": "Analyst", "profile": "analyst"}, {"id": "assistant", "name": "Assistant", "profile": "assistant"}, {"id": "blender", "name": "Blender", "profile": "blender"}, {"id": "cloud", "name": "Cloud", "profile": "cloud"}, {"id": "coder", "name": "Coder", "profile": "coder"}, {"id": "gamemaster", "name": "Gamemaster", "profile": "gamemaster"}, {"id": "github", "name": "Github", "profile": "github"}, {"id": "jayson", "name": "Jayson", "profile": "jayson"}, {"id": "kickstarter", "name": "Kickstarter", "profile": "kickstarter"}, {"id": "mem20", "name": "Mem20", "profile": "mem20"}, {"id": "qamaster", "name": "Qamaster", "profile": "qamaster"}, {"id": "radar", "name": "Radar", "profile": "radar"}, {"id": "releasecoach", "name": "Releasecoach", "profile": "releasecoach"}, {"id": "research", "name": "Research", "profile": "research"}, {"id": "shrink", "name": "Shrink", "profile": "shrink"}, {"id": "unity", "name": "Unity", "profile": "unity"}, {"id": "webdev", "name": "Webdev", "profile": "webdev"}]'
cd /root/hermes-messenger/backend
exec /usr/local/lib/hermes-agent/venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000
