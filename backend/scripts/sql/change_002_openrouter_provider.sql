-- change_002_openrouter_provider.sql
-- Idempotent OpenRouter provider seed.

INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('openrouter', '', 'https://openrouter.ai/api/v1', true)
ON CONFLICT (provider) DO UPDATE
SET base_url = EXCLUDED.base_url,
    is_openai_compatible = EXCLUDED.is_openai_compatible,
    updated_at = NOW();

INSERT INTO public.models (provider, model_type, model_id, thinking, is_default, is_active)
VALUES ('openrouter', 'llm', 'nex-agi/nex-n2-pro:free', true, false, true)
ON CONFLICT (model_id) DO UPDATE
SET provider = EXCLUDED.provider,
    model_type = EXCLUDED.model_type,
    thinking = EXCLUDED.thinking,
    is_active = TRUE,
    updated_at = NOW();

-- Earlier local/dev seeds used Kimi free variants that may be rate-limited.
-- Keep this targeted so user-added OpenRouter models are not affected.
UPDATE public.models
SET is_active = FALSE,
    is_default = FALSE,
    updated_at = NOW()
WHERE provider = 'openrouter'
  AND model_id IN ('moonshotai/kimi-k2.6:free', 'kimi-k2.6');
