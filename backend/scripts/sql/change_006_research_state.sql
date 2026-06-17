-- change_006_research_state.sql
-- Idempotent upgrade for app-owned Deep Search / Deep Research state.

CREATE TABLE IF NOT EXISTS public.research_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    thread_id       UUID REFERENCES public.conversations(thread_id) ON DELETE SET NULL,
    objective       TEXT NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',
    mode            VARCHAR(32) NOT NULL DEFAULT 'deep_search',
    budget          JSONB NOT NULL DEFAULT '{}'::jsonb,
    stop_criteria   JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.research_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES public.research_runs(id) ON DELETE CASCADE,
    step_type       VARCHAR(32) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'completed',
    title           TEXT NOT NULL DEFAULT '',
    query           TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    rationale       TEXT NOT NULL DEFAULT '',
    input           JSONB NOT NULL DEFAULT '{}'::jsonb,
    output          JSONB NOT NULL DEFAULT '{}'::jsonb,
    error           TEXT,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.research_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES public.research_runs(id) ON DELETE CASCADE,
    step_id         UUID REFERENCES public.research_steps(id) ON DELETE SET NULL,
    source_type     VARCHAR(32) NOT NULL DEFAULT 'web',
    source_title    TEXT NOT NULL DEFAULT '',
    source_url      TEXT NOT NULL DEFAULT '',
    claim           TEXT NOT NULL,
    excerpt         TEXT NOT NULL DEFAULT '',
    quality         VARCHAR(32) NOT NULL DEFAULT 'unknown',
    relevance       INTEGER NOT NULL DEFAULT 3,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.research_state_snapshots (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES public.research_runs(id) ON DELETE CASCADE,
    step_id             UUID REFERENCES public.research_steps(id) ON DELETE SET NULL,
    objective           TEXT NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'active',
    subquestions        JSONB NOT NULL DEFAULT '[]'::jsonb,
    known_facts         JSONB NOT NULL DEFAULT '[]'::jsonb,
    gaps                JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflicts           JSONB NOT NULL DEFAULT '[]'::jsonb,
    exhausted_queries   JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_actions        JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids        JSONB NOT NULL DEFAULT '[]'::jsonb,
    budget              JSONB NOT NULL DEFAULT '{}'::jsonb,
    stop_criteria       JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_runs_user_status
ON public.research_runs(user_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_runs_thread
ON public.research_runs(thread_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_steps_run_created
ON public.research_steps(run_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_research_steps_run_type
ON public.research_steps(run_id, step_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_evidence_run_created
ON public.research_evidence(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_evidence_url
ON public.research_evidence(source_url);

CREATE INDEX IF NOT EXISTS idx_research_snapshots_run_created
ON public.research_state_snapshots(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_snapshots_metadata_gin
ON public.research_state_snapshots USING gin (metadata jsonb_path_ops);

ANALYZE public.research_runs;
ANALYZE public.research_steps;
ANALYZE public.research_evidence;
ANALYZE public.research_state_snapshots;
