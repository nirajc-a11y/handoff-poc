#!/bin/sh
set -e

echo "Running database migrations..."
python -m alembic upgrade head || echo "Migrations skipped (may need manual setup)"

echo "Seeding demo data..."
python -m scripts.seed || echo "Seed skipped (data may already exist)"

echo "Starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
