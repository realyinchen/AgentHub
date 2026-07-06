-- change_007_app_provider_configs.sql
-- Durable app-owned provider configuration for memory/research integrations.

CREATE TABLE IF NOT EXISTS public.app_provider_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_key        VARCHAR(64) NOT NULL,
    provider_type       VARCHAR(64) NOT NULL,
    scope               VARCHAR(32) NOT NULL DEFAULT 'global',
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    display_name        VARCHAR(128) NOT NULL DEFAULT '',
    capabilities        JSONB NOT NULL DEFAULT '[]'::jsonb,
    settings            JSONB NOT NULL DEFAULT '{}'::jsonb,
    credentials_ref     VARCHAR(256) NOT NULL DEFAULT '',
    encrypted_api_key   TEXT NOT NULL DEFAULT '',
    health_status       VARCHAR(32) NOT NULL DEFAULT 'unknown',
    health_error_type   VARCHAR(64) NOT NULL DEFAULT '',
    health_error        TEXT NOT NULL DEFAULT '',
    health_duration_ms  INTEGER NOT NULL DEFAULT 0,
    health_checked_at   TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider_key, scope)
);

CREATE INDEX IF NOT EXISTS idx_app_provider_configs_type_enabled
ON public.app_provider_configs(provider_type, enabled);

INSERT INTO public.app_provider_configs (
    provider_key,
    provider_type,
    scope,
    enabled,
    display_name,
    capabilities,
    credentials_ref,
    health_status,
    metadata
)
VALUES
    (
        'mem0',
        'memory',
        'global',
        FALSE,
        'mem0',
        '["memory_recall", "semantic_search"]'::jsonb,
        'env:MEM0_API_KEY',
        'disabled',
        '{"provider_source": "builtin"}'::jsonb
    ),
    (
        'gbrain',
        'research_observation',
        'global',
        FALSE,
        'gbrain',
        '["research_observation", "source_visit", "semantic_search"]'::jsonb,
        'env:GBRAIN_API_KEY',
        'disabled',
        '{"provider_source": "builtin"}'::jsonb
    )
ON CONFLICT (provider_key, scope) DO NOTHING;

ANALYZE public.app_provider_configs;
