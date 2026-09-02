#!/bin/sh
set -e

# Run schema migrations against whatever DATABASE_URL points at (Postgres in
# both docker-compose and on Render), then start the app. $PORT is respected
# so this also works unmodified on Render, which assigns its own port.
flask db upgrade
exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 2 --timeout 60 run:app
