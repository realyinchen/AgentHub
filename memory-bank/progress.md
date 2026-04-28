# Progress

## What Works

- ✅ Backend FastAPI application with SQLite and PostgreSQL support
- ✅ Frontend React + Vite application with hot reload
- ✅ Docker Compose deployment (profiles-based — dev/prod/postgres modes)
- ✅ Database abstraction layer (factory pattern, SQLite & PostgreSQL backends)
- ✅ Chat streaming (SSE), agent execution visualization, thinking mode
- ✅ Model/provider management via web UI
- ✅ Multi-language support (EN/ZH), dark/light theme
- ✅ Healthchecks for all Docker services
- ✅ `.dockerignore` files for optimized builds
- ✅ Named volume data persistence (backend-data, postgres-data, qdrant-data)

## What's Left to Build

- Unit/integration tests
- Vector store full validation (both sqlite-vec and Qdrant)
- Additional agent types (SQL, code, multi-agent)
- Agent graph visualization in React UI
- Conversation search and filtering
- Document upload UI for vector store
- Production Docker Compose (nginx build via `--profile prod`) ✅ done

## Current Status

**Stable** — Core functionality working. Docker deployment uses profiles (dev/prod/postgres); both frontend modes use nginx multi-stage build with nginx.conf.template.

## Known Issues

- Vector store functionality not fully tested
- No automated test suite

## Evolution of Project Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-28 | Removed Docker profiles, simplified to backend+frontend only | Profiles added complexity; PostgreSQL users run their own instances externally |
| 2026-04-28 | Frontend uses nginx multi-stage build in Docker | Both dev and prod modes use nginx; frontend-prod gated behind profiles: ["prod"]; nginx.conf.template for envsubst |
| 2026-04-28 | Bind mounts over named volumes | Easier data inspection, no volume management overhead |
| 2026-04-28 | Added `.dockerignore` files | Faster Docker builds by excluding node_modules, dist, .git |
| 2026-04-28 | Re-introduced Docker profiles (dev/prod/postgres) | Better flexibility: dev for speed, prod for nginx, postgres for optional DB; non-blocking depends_on |
| 2026-04-28 | Switched to named Docker volumes | Better for multi-container data sharing; consistent with Docker best practices |
