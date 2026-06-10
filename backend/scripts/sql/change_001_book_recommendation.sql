-- change_001_book_recommendation.sql
-- Idempotent upgrade for book recommendation features.

INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('lmstudio', 'lm-studio', 'http://127.0.0.1:1234/v1', true)
ON CONFLICT (provider) DO NOTHING;

INSERT INTO public.providers (provider, api_key, base_url, is_openai_compatible)
VALUES ('openai-compatible', 'local', 'http://127.0.0.1:1234/v1', true)
ON CONFLICT (provider) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.books (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(256) NOT NULL,
    subtitle        VARCHAR(256),
    authors         JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary         TEXT,
    rating          NUMERIC(3,1),
    rating_count    INTEGER,
    cover_url       VARCHAR(1024),
    source_name     VARCHAR(64) NOT NULL DEFAULT 'web',
    source_url      VARCHAR(1024) UNIQUE,
    external_id     VARCHAR(128),
    raw_data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_books_title ON public.books(title);
CREATE INDEX IF NOT EXISTS idx_books_source_name ON public.books(source_name);
CREATE INDEX IF NOT EXISTS idx_books_external_id ON public.books(external_id);
CREATE INDEX IF NOT EXISTS idx_books_last_seen_at ON public.books(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_books_raw_data_gin
    ON public.books USING gin (raw_data jsonb_path_ops);

CREATE TABLE IF NOT EXISTS public.book_interactions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    book_id           UUID REFERENCES public.books(id) ON DELETE SET NULL,
    book_title        VARCHAR(256),
    interaction_type  VARCHAR(32) NOT NULL,
    note              TEXT,
    rating            INTEGER,
    raw_data          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_book_interactions_user
ON public.book_interactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_book_interactions_book
ON public.book_interactions(book_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_book_interactions_type
ON public.book_interactions(interaction_type);

CREATE TABLE IF NOT EXISTS public.user_preference_profiles (
    user_id           UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    preferred_tags    JSONB NOT NULL DEFAULT '[]'::jsonb,
    disliked_tags     JSONB NOT NULL DEFAULT '[]'::jsonb,
    favorite_authors  JSONB NOT NULL DEFAULT '[]'::jsonb,
    disliked_authors  JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes             TEXT NOT NULL DEFAULT '',
    profile_summary   TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_preference_profiles_preferred_tags_gin
    ON public.user_preference_profiles USING gin (preferred_tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_user_preference_profiles_favorite_authors_gin
    ON public.user_preference_profiles USING gin (favorite_authors jsonb_path_ops);

ANALYZE public.books;
ANALYZE public.book_interactions;
ANALYZE public.user_preference_profiles;
