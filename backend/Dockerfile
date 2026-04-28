# Backend Dockerfile for AgentHub
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install curl for healthcheck and debugging
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with retry and timeout settings
# Note: asyncpg and psycopg-binary are pure Python / pre-compiled, no system deps needed
RUN pip install --no-cache-dir --retries 5 --timeout 120 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Expose port
EXPOSE 8080

# Run the application via entrypoint script
# - SQLite users: database auto-initializes on first start (idempotent)
# - PostgreSQL users: run init script manually via `docker exec` or during CI/CD
ENTRYPOINT ["./entrypoint.sh"]
