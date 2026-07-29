-- Versioned embedding-space registry.
-- Physical generation tables are created only after the provider's real
-- output dimension has been observed.

CREATE TABLE IF NOT EXISTS public.embedding_spaces (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purpose                 VARCHAR(32) NOT NULL
                            CHECK (purpose IN ('routing', 'memory', 'documents')),
    generation              INTEGER NOT NULL CHECK (generation > 0),
    space_fingerprint       CHAR(64) NOT NULL,
    transport_fingerprint   CHAR(64) NOT NULL DEFAULT '',
    provider                VARCHAR(64) NOT NULL,
    model                   VARCHAR(512) NOT NULL,
    model_revision          VARCHAR(128) NOT NULL DEFAULT '',
    model_origin            VARCHAR(512) NOT NULL DEFAULT '',
    dimensions              INTEGER NOT NULL CHECK (dimensions BETWEEN 1 AND 16000),
    distance_metric         VARCHAR(16) NOT NULL DEFAULT 'cosine'
                            CHECK (distance_metric IN ('cosine')),
    normalized              BOOLEAN NOT NULL DEFAULT FALSE,
    index_kind              VARCHAR(32) NOT NULL
                            CHECK (
                                index_kind IN (
                                    'hnsw_vector',
                                    'hnsw_halfvec',
                                    'exact'
                                )
                            ),
    table_name              VARCHAR(63) NOT NULL UNIQUE,
    status                  VARCHAR(16) NOT NULL DEFAULT 'building'
                            CHECK (
                                status IN ('building', 'ready', 'active', 'failed')
                            ),
    source_space_id         UUID REFERENCES public.embedding_spaces(id)
                            ON DELETE SET NULL,
    source_table_name       VARCHAR(63),
    document_count          INTEGER NOT NULL DEFAULT 0
                            CHECK (document_count >= 0),
    error                   TEXT NOT NULL DEFAULT '',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at            TIMESTAMPTZ,
    UNIQUE (purpose, generation),
    UNIQUE (purpose, space_fingerprint)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_embedding_spaces_active_purpose
    ON public.embedding_spaces (purpose)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_embedding_spaces_status
    ON public.embedding_spaces (purpose, status, generation DESC);

CREATE TABLE IF NOT EXISTS public.embedding_space_bindings (
    purpose          VARCHAR(32) PRIMARY KEY
                     CHECK (purpose IN ('routing', 'memory', 'documents')),
    active_space_id  UUID NOT NULL UNIQUE
                     REFERENCES public.embedding_spaces(id) ON DELETE RESTRICT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.embedding_spaces IS
    'Immutable embedding coordinate spaces and their physical generations';

COMMENT ON TABLE public.embedding_space_bindings IS
    'Atomic logical-purpose to active embedding-generation pointer';
