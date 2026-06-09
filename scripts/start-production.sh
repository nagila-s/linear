#!/bin/sh
set -e

python run_worker.py &

PORT="${PORT:-${APP_PORT:-8000}}"
exec uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT"
