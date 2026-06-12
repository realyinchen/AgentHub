-- change_002_openrouter_provider.sql
-- Idempotent OpenRouter provider seed.

INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('openrouter', '', 'https://openrouter.ai/api/v1', true)
ON CONFLICT (provider) DO UPDATE
SET base_url = EXCLUDED.base_url,
    is_openai_compatible = EXCLUDED.is_openai_compatible,
    updated_at = NOW();

INSERT INTO public.models (provider, connection_id, model_type, model_id, thinking, is_default, is_active)
SELECT 'openrouter', pc.id, 'llm', 'nex-agi/nex-n2-pro:free', true, false, true
FROM public.provider_connections pc
WHERE pc.provider = 'openrouter'
  AND pc.name = 'OpenRouter 默认'
ON CONFLICT DO NOTHING;

UPDATE public.models AS m
SET provider = 'openrouter',
    connection_id = COALESCE(m.connection_id, pc.id),
    model_type = 'llm',
    thinking = true,
    is_active = TRUE,
    updated_at = NOW()
FROM public.provider_connections pc
WHERE m.model_id = 'nex-agi/nex-n2-pro:free'
  AND m.provider = 'openrouter'
  AND pc.provider = 'openrouter'
  AND pc.name = 'OpenRouter 默认';

-- Earlier local/dev seeds used Kimi free variants that may be rate-limited.
-- Keep this targeted so user-added OpenRouter models are not affected.
UPDATE public.models
SET is_active = FALSE,
    is_default = FALSE,
    updated_at = NOW()
WHERE provider = 'openrouter'
  AND model_id IN ('moonshotai/kimi-k2.6:free', 'kimi-k2.6');
