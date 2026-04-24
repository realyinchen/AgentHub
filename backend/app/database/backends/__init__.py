"""
数据库后端实现包

包含 PostgreSQL 和 SQLite 两种后端实现。

结构:
    backends/
    ├── postgres/       # PostgreSQL + Qdrant 实现
    │   ├── db.py
    │   ├── checkpointer.py
    │   └── vectorstore.py
    └── sqlite/         # SQLite + sqlite-vec 实现
        ├── db.py
        ├── checkpointer.py
        └── vectorstore.py
"""
