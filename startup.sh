#!/bin/bash
# Startup script para Azure App Service (Linux - Python)
#
# O App Service injeta a variavel PORT (geralmente 8000). Servimos a aplicacao
# ASGI (Starlette) com gunicorn usando o worker do uvicorn.
#
# - app:        app:app    (objeto Starlette exportado em app.py)
# - workers:    1 worker eh suficiente para SSE; ajuste conforme o plano
# - timeout:    longo para nao matar conexoes SSE
# - keep-alive: alto pelo mesmo motivo

set -e

PORT="${PORT:-8000}"

echo "Starting Azure Pricing MCP server on port ${PORT}"

exec gunicorn app:app \
    --bind=0.0.0.0:${PORT} \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers 1 \
    --timeout 600 \
    --keep-alive 120 \
    --access-logfile '-' \
    --error-logfile '-'
