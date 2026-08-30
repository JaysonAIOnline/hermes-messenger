#!/usr/bin/env bash
# Persistent launcher for the Cloudflare tunnel that exposes the messenger backend.
exec /usr/local/bin/cloudflared tunnel run --token "$(cat /root/hermes-messenger/backend/tunnel.token)" --url http://localhost:8000
