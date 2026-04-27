"""
Database backend implementations package.

Contains PostgreSQL and SQLite backend implementations.

Structure:
    backends/
    ├── postgres/       # PostgreSQL + Qdrant implementation
    │   ├── db.py
    │   ├── checkpointer.py
    │   └── vectorstore.py
    └── sqlite/         # SQLite + sqlite-vec implementation
        ├── db.py
        ├── checkpointer.py
        └── vectorstore.py
"""
