-- AgentHub PostgreSQL Initialization Script
-- This script runs automatically when the PostgreSQL container starts for the first time

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Optional: Verify extension installation
-- SELECT * FROM pg_extension WHERE extname = 'vector';