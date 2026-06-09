#!/bin/sh
set -e
PORT="${PORT:-${APP_PORT:-8000}}"
exec uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT"
