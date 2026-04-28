#!/bin/bash
set -e

# Only auto-initialize database for SQLite + SQLite_Vec combination
# For PostgreSQL, users should run init script manually via exec or during CI/CD
if [ "$DATABASE_TYPE" = "sqlite" ]; then
    echo "SQLite detected - checking if database initialization is needed..."
    python scripts/init_database.py
fi

echo "Starting AgentHub backend..."
exec python run_backend.py