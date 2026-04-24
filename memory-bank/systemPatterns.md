# System Patterns

## System Architecture
- **3-layer architecture**: API → CRUD/Tools → Database (via factory)
- **Factory pattern**: `app/database/factory.py` provides singleton instances via `get_database()`, `get_vectorstore()`, `get_checkpointer()`
- **Interface-based design**: `app/database/interfaces.py` defines abstract interfaces; business code never imports backend implementations

## Key Technical Decisions
- Factory functions cache singleton instances (one per process)
- Session auto-commits on success (safety net for CRUD operations)
- AsyncQdrantClient used for vector search (avoids blocking event loop)
- Lazy class imports via `_import_class()` in factory (avoids circular dependencies)
- Backend type determined by `settings.DATABASE_TYPE` and `settings.VECTORSTORE_TYPE`
- Default config: `postgres`/`qdrant` (matches existing deployments)

## Component Relationships
```
main.py (lifespan)
  └─ init_all() → init_database() + init_vectorstore() + init_checkpointer()
  └─ dispose_all() → dispose vs + cp + db (order matters: vs first, db last)

API routes / Tools
  └─ get_database() → PostgresDatabase (singleton)
  └─ get_vectorstore() → QdrantVectorstore (singleton)
  └─ get_checkpointer() → PostgresCheckpointer (singleton)
  └─ get_saver() → checkpointer.get_saver() → AsyncPostgresSaver
```

## Critical Implementation Paths
- **Chat flow**: API → get_database() → session() → CRUD → commit (auto on session exit)
- **Agent creation**: API → get_database() + get_saver() → create agent with checkpointer
- **Vector search**: Tool → get_vectorstore() → AsyncQdrantClient.search()

## Design Patterns in Use
- **Abstract Factory**: `interfaces.py` + `factory.py` + `backends/`
- **Singleton**: Factory caches instances in module-level variables
- **Context Manager**: `session()` yields session with auto-commit/rollback
- **Strategy**: Backend implementations are interchangeable via config