-- change_009_tavily_provider_config.sql
-- Add Tavily as an app-owned web search provider.

INSERT INTO public.app_provider_configs (
    provider_key,
    provider_type,
    scope,
    enabled,
    display_name,
    capabilities,
    settings,
    credentials_ref,
    health_status,
    metadata
)
VALUES (
    'tavily',
    'web_search',
    'global',
    FALSE,
    'Tavily Search',
    '["web_search"]'::jsonb,
    '{
        "max_results": 3,
        "search_depth": "basic",
        "include_answer": true,
        "include_raw_content": false,
        "health_check_query": "OpenAI",
        "health_check_timeout_seconds": 15
    }'::jsonb,
    'env:TAVILY_API_KEY',
    'disabled',
    '{"provider_source": "builtin"}'::jsonb
)
ON CONFLICT (provider_key, scope) DO NOTHING;

ANALYZE public.app_provider_configs;
