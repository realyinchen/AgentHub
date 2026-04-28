# Active Context

## Current Work Focus

Docker Compose profiles-based optimization — restructured Docker deployment with dev/prod/postgres profiles for fast startup.

## Recent Changes

### Docker Compose Profiles Overhaul (2026-04-28 v3)
- **Profiles-based `docker-compose.yml`**: Three modes — dev (default), prod (`--profile prod`), postgres (`--profile postgres`)
- **Frontend dev & prod both use nginx**: `frontend` service (default) and `frontend-prod` (profile) both use the same multi-stage Dockerfile with nginx. The difference is `frontend-prod` is behind `profiles: ["prod"]` for explicit production targeting.
- **Frontend Dockerfile**: Multi-stage build — Stage 1: `node:24` builds React app; Stage 2: `nginx:stable-alpine3.23-perl` serves static assets. Uses `nginx.conf.template` (envsubst pattern) for dynamic backend proxy config.
- **Build args**: `VITE_API_BASE_URL` (default `/api/v1`), `NGINX_BACKEND_HOST` (default `backend`), `NGINX_BACKEND_PORT` (default `8080`).
- **Named Docker volumes**: `backend-data`, `postgres-data`, `qdrant-data` instead of bind mounts.
- **Non-blocking `depends_on`**: Removed `service_healthy` condition. Frontend just depends on backend starting, not passing health.
- **Optimized healthchecks**: Backend `wget` (interval 10s, timeout 3s, retries 2, start_period 5s). Non-blocking.
- **PostgreSQL + Qdrant**: Both under `profiles: ["postgres"]`. Only start when explicitly requested. PostgreSQL uses `postgres:latest`.
- **Docker network**: `agenthub-network` (bridge) for inter-service communication.
- **README updates**: Both English and Chinese READMEs updated — dev mode no longer described as Vite dev server; both modes described as nginx-based. `nginx.conf.template` documented. `NGINX_BACKEND_HOST` default corrected to `backend`.

### Key Design Decisions
- Docker profiles for flexibility — dev (default, nginx), prod (nginx, explicit profile), postgres (optional DB)
- No blocking healthcheck dependencies — faster startup, no cascading waits
- Both frontend modes use nginx multi-stage build — same Dockerfile, `frontend-prod` just gated behind `profiles: ["prod"]`
- Named volumes over bind mounts for data persistence in Docker

## Next Steps

- Test the full `docker-compose up -d` flow end-to-end
- Test `docker-compose --profile prod up -d` flow
- Test `docker-compose --profile postgres up -d` flow
- Verify backend healthcheck endpoint (`/health`) works correctly in container

## Active Decisions and Considerations

- SQLite mode is the default and recommended for development
- PostgreSQL + Qdrant available via `--profile postgres`
- Both dev and prod frontend use nginx (port 80 mapped to 5173); `frontend-prod` is just profile-gated
- Backend uses `wget` for healthcheck (available in Python slim image)

## Important Patterns and Preferences

- Use `wget` for healthchecks in docker-compose (backend, qdrant); `pg_isready` for postgres
- Environment variables in `.env` files, NOT hardcoded in docker-compose
- Named volumes for data persistence in Docker
- `--profile` flag for optional services (prod, postgres)
