-- Production-only Agent Core: remove development certification storage.
-- Historical change_013..026 files remain immutable migration history.

DROP TABLE IF EXISTS public.agent_shadow_observations;
DROP TABLE IF EXISTS public.agent_capability_certifications;
