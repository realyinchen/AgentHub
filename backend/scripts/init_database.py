"""
Database initialization script.

Supports both PostgreSQL and SQLite backends, both driven by SQL scripts.

PostgreSQL: Executes SQL files from sql/postgres/ directory
SQLite:     Executes SQL files from sql/sqlite/ directory

Usage:
    cd backend
    python scripts/init_database.py

Configuration via .env:
    DATABASE_TYPE=postgres|sqlite  (default: postgres)
"""

import os
import sys
import glob
import asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

DATABASE_TYPE = os.environ.get("DATABASE_TYPE", "postgres")
SQL_DIR = Path(__file__).parent / "sql"


# ── PostgreSQL: Sync engine + SQL files ──────────────────────────────────


def _build_postgres_url() -> str:
    """Build PostgreSQL connection URL from env vars."""
    return (
        f"postgresql+psycopg://{os.environ.get('POSTGRES_USER')}:"
        f"{os.environ.get('POSTGRES_PASSWORD')}@"
        f"{os.environ.get('POSTGRES_HOST')}:{os.environ.get('POSTGRES_PORT')}/"
        f"{os.environ.get('POSTGRES_DB')}"
    )


def _get_sorted_sql_files(db_type: str) -> list[str]:
    """
    Get SQL files for the given database type, sorted by name.

    Looks in sql/postgres/ or sql/sqlite/ subdirectory.
    Sort order: init_database.sql first, then database_change_001.sql, 002.sql, ...
    """
    sql_subdir = SQL_DIR / db_type
    sql_files = glob.glob(str(sql_subdir / "*.sql"))
    sorted_files = sorted(
        sql_files,
        key=lambda x: (
            0 if "init_database.sql" in x else 1,
            int("".join(filter(str.isdigit, Path(x).stem)))
            if "change_" in x
            else 9999,
        ),
    )
    return sorted_files


def _execute_sql_file_sync(engine: sa.engine.Engine, file_path: str) -> None:
    """Execute a single .sql file using a sync engine."""
    print(f"\nExecuting: {Path(file_path).name}")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(sa.text(sql_content))
        print(f"  → Success: {Path(file_path).name}")
    except Exception as e:
        print(f"  → Error in {Path(file_path).name}: {e}")


def _init_postgres() -> None:
    """Initialize PostgreSQL database using SQL files."""
    print("Starting PostgreSQL database schema updates...")
    print(f"SQL directory: {SQL_DIR / 'postgres'}")

    engine = sa.create_engine(_build_postgres_url(), echo=False)
    sql_files = _get_sorted_sql_files("postgres")

    if not sql_files:
        print("No .sql files found in sql/postgres/ folder.")
        return

    print(f"Found {len(sql_files)} SQL files:")
    for f in sql_files:
        print(f"  - {Path(f).name}")

    for file_path in sql_files:
        _execute_sql_file_sync(engine, file_path)

    print("\nAll SQL scripts executed (or skipped if already applied).")
    print("PostgreSQL database schema is up to date.")


# ── SQLite: Async engine + SQL files ────────────────────────────────────


async def _execute_sql_file_async(engine: AsyncEngine, file_path: str) -> None:
    """Execute a single .sql file using an async engine."""
    print(f"\nExecuting: {Path(file_path).name}")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        async with engine.begin() as conn:
            # Split by ; and execute each statement separately
            # (SQLite doesn't support executing multiple statements at once via aiosqlite)
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            for stmt in statements:
                await conn.execute(sa.text(stmt))
        print(f"  → Success: {Path(file_path).name}")
    except Exception as e:
        print(f"  → Error in {Path(file_path).name}: {e}")


async def _init_sqlite_async() -> None:
    """Initialize SQLite database using SQL files."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    print("Starting SQLite database schema updates...")
    print(f"SQL directory: {SQL_DIR / 'sqlite'}")

    db_path = os.environ.get("SQLITE_DATABASE_PATH", "./data/agenthub.db")

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Create async engine
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    sql_files = _get_sorted_sql_files("sqlite")

    if not sql_files:
        print("No .sql files found in sql/sqlite/ folder.")
        return

    print(f"Found {len(sql_files)} SQL files:")
    for f in sql_files:
        print(f"  - {Path(f).name}")

    for file_path in sql_files:
        await _execute_sql_file_async(engine, file_path)

    await engine.dispose()
    print("\nAll SQL scripts executed (or skipped if already applied).")
    print("SQLite database schema is up to date.")


def _init_sqlite() -> None:
    """Initialize SQLite database (sync wrapper)."""
    asyncio.run(_init_sqlite_async())


# ── Main ────────────────────────────────────────────────────────────────


def main():
    print(f"Database type: {DATABASE_TYPE}")
    print("=" * 50)

    if DATABASE_TYPE == "postgres":
        _init_postgres()
    elif DATABASE_TYPE == "sqlite":
        _init_sqlite()
    else:
        print(f"Error: Unsupported DATABASE_TYPE '{DATABASE_TYPE}'")
        print("Supported values: postgres, sqlite")
        sys.exit(1)

    print("\nDatabase initialization complete.")


if __name__ == "__main__":
    main()