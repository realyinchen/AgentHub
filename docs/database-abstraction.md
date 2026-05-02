# Database Abstraction Architecture and Performance Analysis

## Overview

AgentHub adopts a three-layer database abstraction architecture, supporting **SQLite + sqlite-vec** (zero-dependency development mode) and **PostgreSQL + Qdrant** (production-grade mode) backends. Switching backends only requires modifying `.env` configuration, **zero business code changes**.

## Three-Layer Architecture Design

```
Business Layer
  Agent | API | Tools | Utils
         |         |         |
         v         v         v
Factory Layer
  DatabaseFactory + VectorstoreFactory + CheckpointerFactory
  - Dynamically create backend instances based on configuration
  - Singleton pattern for instance caching
  - Dependency inject Embedding function
         |         |         |
         v         v         v
Interface Layer
  DatabaseInterface | VectorstoreInterface | CheckpointInterface
         |         |         |
         v         v         v
Backend Implementations
  SQLite Backend              |  PostgreSQL Backend
  ├── SQLiteDatabase          |  ├── PostgresDatabase
  ├── SqliteVecVectorstore    |  ├── QdrantVectorstore
  └── SqliteCheckpointer      |  └── PostgresCheckpointer
```

## Core Design Principles

### 1. Zero Business Logic Perception
Business code (Agents, APIs, Tools) never directly imports specific backend implementations. All dependencies are abstracted through interfaces, and factories dynamically inject implementations based on configuration.

### 2. Factory Layer Singleton
Factory functions in `factory.py` use module-level variables to cache singleton instances:
- Database engine: Globally reused (connection pool)
- Vectorstore client: Thread-safe, connection reuse
- Checkpointer: LangGraph Saver instance

### 3. Configuration-Driven Switching
Controlled through two independent configuration items in `.env`:
- `DATABASE_TYPE`: `sqlite` or `postgres`
- `VECTORSTORE_TYPE`: `sqlite_vec` or `qdrant`

## Backend Comparison

| Dimension | SQLite Backend (Default) | PostgreSQL Backend (Production) |
|-----------|-------------------------|---------------------------------|
| **Database** | SQLAlchemy + aiosqlite | SQLAlchemy + asyncpg |
| **Checkpointer** | AsyncSqliteSaver (LangGraph official) | AsyncPostgresSaver (LangGraph official) |
| **Vector Storage** | sqlite-vec (embedded) | Qdrant (independent service) |
| **External Dependencies** | **None** | PostgreSQL + Qdrant service |
| **Concurrency Capability** | Single-write multi-read (suitable for <200 QPS) | Full MVCC (supports 100+ concurrent users) |
| **Deployment Complexity** | Extremely low (auto-creates files) | Medium (requires Docker or independent deployment) |
| **Best Scenario** | Development, testing, demo, personal projects | Production environment, high concurrency, team collaboration |

## Score Semantic Unification

Different vector backends have different similarity score output formats; AgentHub has unified them at the interface layer:

| Backend | Native Output | Meaning | Unified Output | Conversion Method |
|---------|--------------|---------|----------------|------------------|
| Qdrant | score (0~1) | Cosine similarity, higher is more similar | score (0~1) | No conversion needed |
| sqlite-vec | distance (0~2) | Cosine distance, lower is more similar | score (0~1) | `score = 1.0 - distance` |

**Convention**: `VectorstoreInterface.search_with_embedding()` must return normalized `score` (0~1).

## ORM Model Compatibility

| PostgreSQL Type | SQLAlchemy Generic Type | SQLite Storage |
|----------------|------------------------|---------------|
| `postgresql.UUID` | `sqlalchemy.Uuid` | TEXT (string form) |
| `postgresql.JSONB` | `sqlalchemy.JSON` | TEXT |

## Performance Benchmark Testing

### Relational Database Performance

| Operation | SQLite | PostgreSQL | Multiple |
|-----------|--------|------------|----------|
| Simple point query (primary key) | **0.1ms** | 1-2ms | PG 10-20x slower |
| Session list query (pagination) | **5ms** | 50-100ms | PG 10-20x slower |
| High concurrency writes (100 concurrent) | ❌ Serialized queuing | ✅ 20-50ms | PG 10x+ faster |
| Complex JOIN queries | ❌ Limited support | ✅ Excellent | - |

**Key Conclusion**: SQLite is faster in low-concurrency read scenarios, PostgreSQL has obvious advantages in high-concurrency write and complex query scenarios.

### Vector Database Performance

| Dataset Size | sqlite-vec | Qdrant (HNSW) |
|--------------|-----------|---------------|
| < 10K vectors | ✅ 5-10ms | ✅ 10-20ms |
| 10K - 100K vectors | ⚠️ 50-200ms | ✅ 20-50ms |
| > 100K vectors | ❌ Second-level latency | ✅ 30-80ms |

**Qdrant HNSW Index Configuration**:
```python
hnsw_config={
    "m": 16,              # Number of connections per node
    "ef_construct": 200,  # Search factor during construction
}
ef_search=200              # Search factor during query
```

## PostgreSQL Connection Pool Configuration

```python
# backend/app/database/backends/postgres/db.py
pool_size=20,              # Base connection count
max_overflow=30,           # Overflow connection count (peak max 50 connections)
pool_recycle=300,          # Connection recycle time (seconds)
pool_use_lifo=True,        # LIFO mode (better performance)
pool_pre_ping=True,        # Connection health check
```

**Supported Scenarios**:
- Regular: 100+ concurrent users
- Peak: Supports 50 active database connections

## Production-Grade Singleton Specification

| Component | Singleton? | Reason |
|-----------|------------|--------|
| Database Engine | ✅ Yes | Global connection pool reuse, avoid repeated creation |
| Database Session | ❌ No | Request-level isolation, has transaction state, not thread-safe |
| Qdrant Client | ✅ Yes | No transaction, thread-safe, HTTP connection reuse |
| Checkpointer | ✅ Yes | LangGraph Saver instance can be reused |

## Transaction Commit Specification

**Global Mandatory Rule**:
- All business code (APIs, Services, CRUD) **prohibited** from calling `commit()` / `rollback()` themselves
- Unified handling by `db.session()` context manager

**Standard Pattern**:
```python
async with db.session() as session:
    # Business logic: Only add/update/delete, zero transaction operations
    await crud.do_something(session, ...)
# Context exit auto commit, exception auto rollback, always close
```

## Steps to Add New Backend

1. Implement `DatabaseInterface` in `backends/<name>/db.py`
2. Implement `VectorstoreInterface` in `backends/<name>/vectorstore.py`
3. Implement `CheckpointInterface` in `backends/<name>/checkpointer.py`
4. Register in `factory.py` (`_DB_BACKENDS`, `_VS_BACKENDS`, `_CP_BACKENDS`)
5. If new configuration items are needed, update `config.py`
6. Update `.env.example` and documentation

**No modifications required**: Any business layer code (Agents, APIs, Tools, Utils)

## Known Trade-Offs

| Decision | Benefit | Cost |
|----------|---------|------|
| Factory pattern + Interface abstraction | Zero business perception, easy to extend | Negligible indirect call overhead (<1% of API response time) |
| Embedding function DI | Vectorstore does not depend on ModelManager | Slightly increased complexity |
| Unified Score semantics | Business layer only processes one format | sqlite-vec requires additional conversion |
| Docker Profiles | One Compose file supports multiple modes | Learning curve (need to understand `--profile`) |

## Scenario Recommendations

| Scenario | Recommended Stack |
|----------|-------------------|
| Local development / Rapid prototyping | **SQLite + sqlite-vec** |
| Demo / Personal projects | **SQLite + sqlite-vec** |
| Production (< 100 concurrent users) | **SQLite + sqlite-vec** (or PG if write-intensive) |
| Production (100+ concurrent users) | **PostgreSQL + Qdrant** |
| Production + Heavy RAG | **PostgreSQL + Qdrant** |
| Team collaboration development | **PostgreSQL + Qdrant** |