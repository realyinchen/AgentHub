# 数据库抽象架构文档

## 核心设计原则

### 1. 业务逻辑零感知
- **目标**: agents、api、tools 层代码完全不感知底层数据库类型
- **实现**: 通过工厂模式和接口抽象，业务层只依赖接口不依赖具体实现
- **效果**: 切换数据库类型不需要修改任何业务代码

### 2. 工厂层一劳永逸
- **目标**: factory.py 只负责根据配置创建实例
- **实现**: 注册表模式，添加新后端只需要注册到工厂
- **效果**: 表结构变更只影响具体后端实现，不改动工厂

### 3. 配置驱动切换
- **目标**: 通过 `.env` 配置项切换后端
- **实现**: `DATABASE_TYPE` 和 `VECTORSTORE_TYPE` 两个独立配置
- **效果**: 同一代码库支持多种部署场景

---

## 三层架构

```
┌─────────────────────────────────────────────────────────┐
│ 业务层 (Business Logic)                                   │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│ │  Agent   │ │   API    │ │  Tools   │ │  Utils   │   │
│ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
└──────┼──────────────┼──────────────┼──────────────┼─────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────┐
│ 工厂层 (Factory Layer)                                    │
│   DatabaseFactory + VectorstoreFactory                    │
│   - 根据配置动态创建后端实例                                │
│   - 注入嵌入函数到向量存储                                  │
└──────┬──────────────┬──────────────┬──────────────┬─────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────┐
│ 接口层 (Interface Layer)                                  │
│   DatabaseInterface + CheckpointInterface                │
│   VectorstoreInterface                                    │
└──────┬──────────────┬──────────────┬──────────────┬─────┘
       │              │              │              │
       ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────┐
│ 后端实现层 (Backend Implementations)                      │
│                                                           │
│  PostgreSQL        │        SQLite                        │
│  ┌──────────────┐  │  ┌──────────────┐                   │
│  │   Postgres   │  │  │     SQLite   │                   │
│  │   Database   │  │  │    Database  │                   │
│  ├──────────────┤  │  ├──────────────┤                   │
│  │ Postgres CP  │  │  │   SQLite CP  │                   │
│  ├──────────────┤  │  ├──────────────┤                   │
│  │    Qdrant    │  │  │  sqlite-vec  │                   │
│  └──────────────┘  │  └──────────────┘                   │
└─────────────────────────────────────────────────────────┘
```

---

## 接口定义

### DatabaseInterface

```python
class DatabaseInterface(ABC):
    @abstractmethod
    def session(self) -> AsyncContextManager[AsyncSession]:
        """获取数据库会话（业务层用这个）"""

    @abstractmethod
    async def execute_query(self, sql: str, params: dict = None) -> list[dict]:
        """执行原生 SQL 查询（脚本初始化用）"""

    @abstractmethod
    async def initialize(self) -> None:
        """初始化数据库连接、创建表结构"""

    @abstractmethod
    async def dispose(self) -> None:
        """释放数据库连接资源"""
```

### CheckpointInterface

```python
class CheckpointInterface(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        """初始化 checkpointer 连接"""

    @abstractmethod
    async def dispose(self) -> None:
        """释放 checkpointer 连接"""

    @abstractmethod
    def get_saver(self):
        """获取 LangGraph 兼容的 Saver 实例"""
```

### VectorstoreInterface

```python
class VectorstoreInterface(ABC):
    _embed_fn: Optional[Callable] = None

    def set_embed_fn(self, fn: Callable) -> None:
        """注入嵌入函数（由工厂调用，业务代码不应直接使用）"""
        self._embed_fn = fn

    @abstractmethod
    async def initialize(self) -> None:
        """初始化向量存储连接"""

    @abstractmethod
    async def dispose(self) -> None:
        """释放向量存储连接"""

    @abstractmethod
    async def search(self, collection_name: str, query_text: str, limit: int = 5) -> list[dict]:
        """文本搜索：内部调用 _embed_fn 转向量后调用 search_with_embedding"""

    @abstractmethod
    async def search_with_embedding(self, collection_name: str, embedding: list[float], limit: int = 5) -> list[dict]:
        """向量搜索：返回统一格式的搜索结果"""

    @abstractmethod
    async def add_documents(self, collection_name: str, documents: list[str], embeddings: list[list[float]]) -> list[str]:
        """批量添加文档到向量存储"""
```

---

## 工厂模式实现

### 注册表模式

```python
# 后端注册表
_DB_BACKENDS = {
    "postgres": PostgresDatabase,
    "sqlite": SQLiteDatabase,
}

_CP_BACKENDS = {
    "postgres": PostgresCheckpointer,
    "sqlite": SqliteCheckpointer,
}

_VS_BACKENDS = {
    "qdrant": QdrantVectorstore,
    "sqlite_vec": SqliteVecVectorstore,
}

# 工厂函数
def get_database() -> DatabaseInterface:
    backend_cls = _DB_BACKENDS[settings.DATABASE_TYPE]
    return backend_cls()
```

### 嵌入函数依赖注入

```python
async def _default_embed_fn(text: str) -> list[float]:
    """默认嵌入函数：从 ModelManager 获取模型并嵌入"""
    model_id, api_key = await ModelManager.get_embedding_model_instance()
    response = await litellm.aembedding(model=model_id, input=[text], api_key=api_key)
    return response.data[0]["embedding"]

def get_vectorstore() -> VectorstoreInterface:
    vs = cls()
    vs.set_embed_fn(_default_embed_fn)  # 注入嵌入函数
    return vs
```

---

## 后端实现要点

### PostgreSQL 后端

| 组件 | 实现依赖 | 特点 |
|------|----------|------|
| Database | SQLAlchemy + asyncpg | 连接池，高并发 |
| Checkpointer | AsyncPostgresSaver | LangGraph 官方支持 |
| Vectorstore | qdrant-client | 生产级向量数据库 |

### SQLite 后端

| 组件 | 实现依赖 | 特点 |
|------|----------|------|
| Database | SQLAlchemy + aiosqlite | StaticPool 单连接模式 |
| Checkpointer | AsyncSqliteSaver | LangGraph 官方支持 |
| Vectorstore | sqlite-vec 扩展 | 零依赖，嵌入式向量存储 |

---

## 评分语义统一

| 后端 | 原始输出 | 含义 | 统一后 | 转换公式 |
|------|----------|------|--------|----------|
| Qdrant | score (0~1) | 余弦相似度，越大越相似 | score (0~1) | 无需转换 |
| sqlite-vec | distance (0~2) | 余弦距离，越小越相似 | score (0~1) | score = 1.0 - distance |

**约定**: `VectorstoreInterface.search_with_embedding()` 返回的 `score` 字段**必须**是余弦相似度（0~1，越大越相似）。

---

## Docker 部署架构

### 根目录 docker-compose.yml (Profiles 模式)

```
# SQLite Mode (default)
docker-compose up -d
├── backend
│   └── volumes: agenthub-backend-data → /app/data
└── frontend

# PostgreSQL Mode (with --profile postgres)
docker-compose --profile postgres up -d
├── postgres
│   └── volumes: agenthub-postgres-data
├── qdrant
│   └── volumes: agenthub-qdrant-data
├── backend
│   └── network: connects to postgres + qdrant via service names
└── frontend
```

### 关键设计

1. **同一 Docker 镜像**: 后端 Dockerfile 包含所有依赖（asyncpg + aiosqlite + sqlite-vec），无需重建即可切换后端
2. **Docker Network DNS**: PG 模式下 `POSTGRES_HOST=postgres`、`QDRANT_HOST=qdrant`，使用 Docker 内部 DNS
3. **数据持久化**: 三个独立 Docker Volume，互不干扰
4. **健康检查**: 所有服务都有健康检查，前端等待后端就绪后启动

---

## ORM 模型兼容性处理

### PostgreSQL 专有类型 → 通用类型

| PostgreSQL 类型 | SQLAlchemy 通用类型 | SQLite 存储形式 |
|-----------------|---------------------|-----------------|
| `postgresql.UUID(as_uuid=True)` | `sqlalchemy.Uuid` | TEXT (字符串形式) |
| `postgresql.JSONB` | `sqlalchemy.JSON` | TEXT |

### `server_default` 兼容性

```python
# 之前（PostgreSQL 专有）
updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# 之后（跨数据库兼容）
updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
```

**原因**: SQLite 不支持 `server_default=func.now()` 在 UPDATE 时自动触发，需依赖 SQLAlchemy 的 Python 侧回调。

---

## 添加新后端的流程

1. 实现 `DatabaseInterface` 接口
2. 实现 `CheckpointInterface` 接口
3. 实现 `VectorstoreInterface` 接口
4. 在 `factory.py` 的 `_DB_BACKENDS`、`_CP_BACKENDS`、`_VS_BACKENDS` 中注册
5. 更新 `config.py` 添加新的配置项（如需要）
6. 更新 `.env.example` 文档
7. 更新 `README.md` 文档

**无需修改**: 任何业务层代码（agents、api、tools、utils）

---

## 测试策略

### 单元测试
- 测试每个后端实现的接口方法
- 测试工厂根据配置正确创建实例

### 集成测试
- 端到端测试：SQLite 模式完整运行
- 端到端测试：PostgreSQL 模式完整运行
- 切换测试：两种模式下相同业务流程结果一致

### 性能测试
- SQLite 模式并发极限（单连接瓶颈）
- PostgreSQL 模式并发能力
- 向量搜索响应时间对比

---

## 已知限制与权衡

### SQLite 限制
1. **并发写入**: 不支持多连接并发写，使用 `StaticPool` 单连接模式
2. **复杂查询**: JSON 查询功能有限，不支持 `jsonb_path_query` 等 PG 专有操作
3. **写入性能**: WAL 模式下写入性能仍低于 PG，适合中小型应用

### 架构权衡

| 决策 | 收益 | 代价 |
|------|------|------|
| 工厂模式 + 接口抽象 | 业务层零感知，易扩展 | 增加一层间接调用的开销 |
| 嵌入函数依赖注入 | Vectorstore 不依赖 ModelManager | 增加一点复杂度 |
| 统一评分语义 | 业务层无需处理两种评分 | sqlite-vec 实现多一步转换 |
| Docker Profiles | 一个 compose 文件支持两种模式 | 学习成本（需要知道 --profile） |

---

## 文件结构总览

```
backend/app/database/
├── base.py                  # 接口定义
├── factory.py               # 工厂实现
├── __init__.py              # 导出工厂函数
└── backends/
    ├── __init__.py
    ├── postgres/
    │   ├── __init__.py
    │   ├── db.py            # PostgresDatabase
    │   ├── checkpointer.py  # PostgresCheckpointer
    │   └── vectorstore.py   # QdrantVectorstore
    └── sqlite/
        ├── __init__.py
        ├── db.py            # SQLiteDatabase
        ├── checkpointer.py  # SqliteCheckpointer
        └── vectorstore.py   # SqliteVecVectorstore