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

## Production Standards (PostgreSQL + Qdrant)
### 单例使用规范
- **PostgreSQL Engine**: 必须单例（全局连接池复用）
- **PostgreSQL Session**: 禁止单例（请求级隔离，有事务状态，非线程安全）
- **Qdrant Client**: 推荐单例（无事务、线程安全、连接复用）

### 事务 Commit 规范
- **全局强制**：所有业务代码（API、Services、CRUD）禁止自行 commit/rollback
- **统一处理**：由 `db.session()` 上下文管理器统一 commit/rollback/close
- **唯一例外**：仅离线脚本允许自行 commit

### 实现模式
```python
# db.session() 标准模式
async with db.session() as session:
    # 业务逻辑：仅 add/update/delete，零事务操作
    await crud.do_something(session, ...)
# 上下文退出自动 commit，异常自动 rollback，始终 close
```

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