#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p uploads outputs

exec uvicorn app.main:app --host 127.0.0.1 --port 8000
