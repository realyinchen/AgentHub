-- change_004_provider_connections.sql
-- Idempotent Provider -> Connection -> Model migration.

CREATE TABLE IF NOT EXISTS public.provider_connections (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider             VARCHAR(64) NOT NULL REFERENCES public.providers(provider),
    name                 VARCHAR(128) NOT NULL,
    preset_type          VARCHAR(32) NOT NULL DEFAULT 'default',
    api_key              TEXT NOT NULL DEFAULT '',
    base_url             VARCHAR(512),
    extra_headers_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_connections_provider_name
ON public.provider_connections(provider, name);

CREATE INDEX IF NOT EXISTS idx_provider_connections_provider
ON public.provider_connections(provider);

CREATE INDEX IF NOT EXISTS idx_provider_connections_active
ON public.provider_connections(is_active);

-- Protocol providers. Legacy lmstudio may still exist in older DBs but should
-- be represented as an openai-compatible connection.
INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES
    ('dashscope', '', NULL, false),
    ('openrouter', '', 'https://openrouter.ai/api/v1', true),
    ('openai-compatible', 'local', 'http://127.0.0.1:1234/v1', true)
ON CONFLICT (provider) DO NOTHING;

-- Default first-party/gateway connections keep any existing provider secret.
INSERT INTO public.provider_connections (provider, name, preset_type, api_key, base_url, is_active)
SELECT provider,
       CASE provider
           WHEN 'dashscope' THEN 'DashScope 默认'
           WHEN 'openrouter' THEN 'OpenRouter 默认'
           ELSE provider || ' 默认'
       END,
       'default',
       api_key,
       base_url,
       true
FROM public.providers
WHERE provider IN ('dashscope', 'openrouter')
ON CONFLICT (provider, name) DO UPDATE
SET api_key = CASE
        WHEN public.provider_connections.api_key = '' THEN EXCLUDED.api_key
        ELSE public.provider_connections.api_key
    END,
    base_url = COALESCE(public.provider_connections.base_url, EXCLUDED.base_url),
    is_active = true,
    updated_at = NOW();

-- LM Studio is a preset connection under openai-compatible, not a provider.
INSERT INTO public.provider_connections (provider, name, preset_type, api_key, base_url, is_active)
SELECT 'openai-compatible',
       'LM Studio 本地',
       'lmstudio',
       COALESCE(NULLIF(lm.api_key, ''), NULLIF(oc.api_key, ''), 'local'),
       COALESCE(lm.base_url, oc.base_url, 'http://127.0.0.1:1234/v1'),
       true
FROM public.providers oc
LEFT JOIN public.providers lm ON lm.provider = 'lmstudio'
WHERE oc.provider = 'openai-compatible'
ON CONFLICT (provider, name) DO UPDATE
SET api_key = CASE
        WHEN public.provider_connections.api_key = '' THEN EXCLUDED.api_key
        ELSE public.provider_connections.api_key
    END,
    base_url = COALESCE(public.provider_connections.base_url, EXCLUDED.base_url),
    preset_type = 'lmstudio',
    is_active = true,
    updated_at = NOW();

-- Optional local presets are created disabled until the user configures them.
INSERT INTO public.provider_connections (provider, name, preset_type, api_key, base_url, is_active)
VALUES
    ('openai-compatible', 'Ollama 本地', 'ollama', 'local', 'http://127.0.0.1:11434/v1', false),
    ('openai-compatible', 'vLLM', 'vllm', 'local', 'http://127.0.0.1:8000/v1', false),
    ('openai-compatible', '自定义 API', 'custom', '', NULL, false)
ON CONFLICT (provider, name) DO NOTHING;

ALTER TABLE public.models
ADD COLUMN IF NOT EXISTS connection_id UUID REFERENCES public.provider_connections(id);

-- Legacy lmstudio models move under the openai-compatible LM Studio connection.
UPDATE public.models AS m
SET provider = 'openai-compatible',
    connection_id = pc.id,
    updated_at = NOW()
FROM public.provider_connections AS pc
WHERE m.provider = 'lmstudio'
  AND pc.provider = 'openai-compatible'
  AND pc.name = 'LM Studio 本地';

-- Backfill remaining models to the first active connection for their provider.
WITH first_connections AS (
    SELECT DISTINCT ON (provider) provider, id
    FROM public.provider_connections
    WHERE is_active = true
    ORDER BY provider, created_at, name
)
UPDATE public.models AS m
SET connection_id = fc.id,
    updated_at = NOW()
FROM first_connections AS fc
WHERE m.connection_id IS NULL
  AND m.provider = fc.provider;

-- Allow identical provider model IDs under different connections.
ALTER TABLE public.models DROP CONSTRAINT IF EXISTS models_model_id_key;
DROP INDEX IF EXISTS public.idx_models_model_id;
CREATE INDEX IF NOT EXISTS idx_models_model_id ON public.models(model_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_models_connection_model_id
ON public.models(connection_id, model_id)
WHERE connection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_models_connection_id
ON public.models(connection_id);

ANALYZE public.provider_connections;
ANALYZE public.models;

