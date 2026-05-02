# 数据库抽象架构与性能分析

## 概述

AgentHub 采用三层数据库抽象架构，支持 **SQLite + sqlite-vec**（零依赖开发模式）和 **PostgreSQL + Qdrant**（生产级模式）两种后端。切换后端仅需修改 `.env` 配置，**业务代码零改动**。

## 三层架构设计

```
业务层 (Business Layer)
  Agent | API | Tools | Utils
         |         |         |
         v         v         v
工厂层 (Factory Layer)
  DatabaseFactory + VectorstoreFactory + CheckpointerFactory
  - 基于配置动态创建后端实例
  - 单例模式缓存实例
  - 依赖注入 Embedding 函数
         |         |         |
         v         v         v
接口层 (Interface Layer)
  DatabaseInterface | VectorstoreInterface | CheckpointInterface
         |         |         |
         v         v         v
后端实现 (Backend Implementations)
  SQLite Backend              |  PostgreSQL Backend
  ├── SQLiteDatabase          |  ├── PostgresDatabase
  ├── SqliteVecVectorstore    |  ├── QdrantVectorstore
  └── SqliteCheckpointer      |  └── PostgresCheckpointer
```

## 核心设计原则

### 1. 零业务逻辑感知

业务代码（Agents、API、Tools）从不直接导入具体后端实现。所有依赖都通过接口抽象，工厂根据配置动态注入实现。

### 2. 工厂层单例

`factory.py` 中的工厂函数使用模块级变量缓存单例实例：
- Database 引擎：全局复用（连接池）
- Vectorstore 客户端：线程安全，连接复用
- Checkpointer：LangGraph Saver 实例

### 3. 配置驱动切换

通过 `.env` 中的两个独立配置项控制：
- `DATABASE_TYPE`: `sqlite` 或 `postgres`
- `VECTORSTORE_TYPE`: `sqlite_vec` 或 `qdrant`

## 后端对比

| 维度 | SQLite Backend (默认) | PostgreSQL Backend (生产) |
|------|----------------------|--------------------------|
| **数据库** | SQLAlchemy + aiosqlite | SQLAlchemy + asyncpg |
| **Checkpointer** | AsyncSqliteSaver (LangGraph 官方) | AsyncPostgresSaver (LangGraph 官方) |
| **向量存储** | sqlite-vec (嵌入式) | Qdrant (独立服务) |
| **外部依赖** | **无** | PostgreSQL + Qdrant 服务 |
| **并发能力** | 单写多读（适合 < 200 QPS） | 完整 MVCC（支持 100+ 并发用户） |
| **部署复杂度** | 极低（自动创建文件） | 中等（需要 Docker 或独立部署） |
| **最佳场景** | 开发、测试、Demo、个人项目 | 生产环境、高并发、团队协作 |

## Score 语义统一

不同向量后端的相似度分数输出格式不同，AgentHub 在接口层做了统一：

| 后端 | 原生输出 | 含义 | 统一输出 | 转换方式 |
|------|---------|------|---------|---------|
| Qdrant | score (0~1) | Cosine 相似度，越高越相似 | score (0~1) | 无需转换 |
| sqlite-vec | distance (0~2) | Cosine 距离，越低越相似 | score (0~1) | `score = 1.0 - distance` |

**约定**：`VectorstoreInterface.search_with_embedding()` 必须返回归一化的 `score` (0~1)。

## ORM 模型兼容性

| PostgreSQL 类型 | SQLAlchemy 通用类型 | SQLite 存储 |
|----------------|-------------------|------------|
| `postgresql.UUID` | `sqlalchemy.Uuid` | TEXT (字符串形式) |
| `postgresql.JSONB` | `sqlalchemy.JSON` | TEXT |

## 性能基准测试

### 关系型数据库性能

| 操作 | SQLite | PostgreSQL | 倍数 |
|------|--------|------------|------|
| 简单点查询 (主键) | **0.1ms** | 1-2ms | PG 慢 10-20x |
| 会话列表查询 (分页) | **5ms** | 50-100ms | PG 慢 10-20x |
| 高并发写入 (100 并发) | ❌ 序列化排队 | ✅ 20-50ms | PG 快 10x+ |
| 复杂 JOIN 查询 | ❌ 有限支持 | ✅ 优秀 | - |

**关键结论**：SQLite 在低并发读取场景更快，PostgreSQL 在高并发写入和复杂查询场景优势明显。

### 向量数据库性能

| 数据集规模 | sqlite-vec | Qdrant (HNSW) |
|-----------|-----------|--------------|
| < 10K 向量 | ✅ 5-10ms | ✅ 10-20ms |
| 10K - 100K 向量 | ⚠️ 50-200ms | ✅ 20-50ms |
| > 100K 向量 | ❌ 秒级延迟 | ✅ 30-80ms |

**Qdrant HNSW 索引配置**：
```python
hnsw_config={
    "m": 16,              # 每个节点的连接数
    "ef_construct": 200,  # 构建时搜索因子
}
ef_search=200              # 查询时搜索因子
```

## PostgreSQL 连接池配置

```python
# backend/app/database/backends/postgres/db.py
pool_size=20,              # 基础连接数
max_overflow=30,           # 溢出连接数（峰值最多 50 连接）
pool_recycle=300,          # 连接回收时间（秒）
pool_use_lifo=True,        # LIFO 模式（性能更好）
pool_pre_ping=True,        # 连接健康检查
```

**支持场景**：
- 常规：100+ 并发用户
- 峰值：支持 50 个活跃数据库连接

## 生产级单例规范

| 组件 | 单例？ | 原因 |
|------|--------|------|
| Database Engine | ✅ 是 | 全局连接池复用，避免重复创建 |
| Database Session | ❌ 否 | 请求级别隔离，有事务状态，非线程安全 |
| Qdrant Client | ✅ 是 | 无事务，线程安全，HTTP 连接复用 |
| Checkpointer | ✅ 是 | LangGraph Saver 实例可复用 |

## 事务 Commit 规范

**全局强制规则**：
- 所有业务代码（API、Services、CRUD）**禁止**自行调用 `commit()` / `rollback()`
- 由 `db.session()` 上下文管理器统一处理

**标准模式**：
```python
async with db.session() as session:
    # 业务逻辑：仅 add/update/delete，零事务操作
    await crud.do_something(session, ...)
# 上下文退出自动 commit，异常自动 rollback，始终 close
```

## 添加新后端的步骤

1. 实现 `DatabaseInterface` 在 `backends/<name>/db.py`
2. 实现 `VectorstoreInterface` 在 `backends/<name>/vectorstore.py`
3. 实现 `CheckpointInterface` 在 `backends/<name>/checkpointer.py`
4. 在 `factory.py` 中注册（`_DB_BACKENDS`, `_VS_BACKENDS`, `_CP_BACKENDS`）
5. 如需新配置项，更新 `config.py`
6. 更新 `.env.example` 和文档

**无需修改**：任何业务层代码（Agents、API、Tools、Utils）

## 已知权衡

| 决策 | 收益 | 代价 |
|------|------|------|
| 工厂模式 + 接口抽象 | 零业务感知，易于扩展 | 可忽略的间接调用开销（< API 响应时间的 1%） |
| Embedding 函数 DI | Vectorstore 不依赖 ModelManager | 略微增加复杂度 |
| 统一 Score 语义 | 业务层只处理一种格式 | sqlite-vec 需要额外转换 |
| Docker Profiles | 一个 Compose 文件支持多种模式 | 学习曲线（需要了解 `--profile`） |

## 场景推荐

| 场景 | 推荐栈 |
|------|--------|
| 本地开发 / 快速原型 | **SQLite + sqlite-vec** |
| Demo / 个人项目 | **SQLite + sqlite-vec** |
| 生产（< 100 并发用户） | **SQLite + sqlite-vec**（或 PG 如果写密集） |
| 生产（100+ 并发用户） | **PostgreSQL + Qdrant** |
| 生产 + 重型 RAG | **PostgreSQL + Qdrant** |
| 团队协作开发 | **PostgreSQL + Qdrant** |