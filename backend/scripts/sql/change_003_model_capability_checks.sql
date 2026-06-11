-- change_003_model_capability_checks.sql
-- Idempotent model runtime capability check history.

CREATE TABLE IF NOT EXISTS public.model_capability_checks (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id                 UUID NOT NULL REFERENCES public.models(id) ON DELETE CASCADE,
    provider                 VARCHAR(64) NOT NULL,
    provider_model_id        VARCHAR(256) NOT NULL,
    checked_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chat_ok                  BOOLEAN NOT NULL DEFAULT FALSE,
    thinking_request_ok      BOOLEAN,
    reasoning_text_ok        BOOLEAN,
    streaming_reasoning_ok   BOOLEAN,
    reasoning_field_path     VARCHAR(128),
    latency_ms               INTEGER,
    error_type               VARCHAR(64),
    last_error               TEXT,
    raw_summary              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_model_capability_model_checked
ON public.model_capability_checks(model_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_capability_provider_model
ON public.model_capability_checks(provider, provider_model_id);
CREATE INDEX IF NOT EXISTS idx_model_capability_reasoning
ON public.model_capability_checks(reasoning_text_ok);
