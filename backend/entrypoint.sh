#!/bin/bash
set -e

# Database initialization is handled externally via:
#   python scripts/init_database.py
# Run it manually or during CI/CD against a running PostgreSQL instance.

echo "Starting AgentHub backend..."
exec python run_backend.py