-- Migration: Add token columns to trace_executions table
-- Date: 2026-06-12
-- Description: Adds input_tokens, output_tokens, total_tokens columns to
-- trace_executions so daily stats can be computed from per-turn timestamps
-- instead of conversations.created_at (which stays fixed for long-lived
-- conversations like WeChat).

ALTER TABLE trace_executions
ADD COLUMN IF NOT EXISTS input_tokens BIGINT NOT NULL DEFAULT 0;

ALTER TABLE trace_executions
ADD COLUMN IF NOT EXISTS output_tokens BIGINT NOT NULL DEFAULT 0;

ALTER TABLE trace_executions
ADD COLUMN IF NOT EXISTS total_tokens BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN trace_executions.input_tokens IS 'Input tokens for this turn';
COMMENT ON COLUMN trace_executions.output_tokens IS 'Output tokens for this turn';
COMMENT ON COLUMN trace_executions.total_tokens IS 'Total tokens for this turn';