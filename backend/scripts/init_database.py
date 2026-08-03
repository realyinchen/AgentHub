"""
Database initialization script — PostgreSQL only.

Executes SQL files from sql/ directory in order.

Usage:
    cd backend
    python scripts/init_database.py

Configuration via .env:
    POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
"""

import os
import re
import sqlalchemy as sa
from sqlalchemy import text
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

SQL_DIR = Path(__file__).parent / "sql"
_CHANGE_NUMBER = re.compile(r"^change_(\d+)")


def _build_postgres_url() -> str:
    """Build PostgreSQL connection URL from env vars."""
    ssl_mode = os.environ.get("POSTGRES_SSL_MODE", "disable")
    return (
        f"postgresql+psycopg://{os.environ.get('POSTGRES_USER')}:"
        f"{os.environ.get('POSTGRES_PASSWORD')}@"
        f"{os.environ.get('POSTGRES_HOST')}:{os.environ.get('POSTGRES_PORT')}/"
        f"{os.environ.get('POSTGRES_DB')}?sslmode={ssl_mode}&connect_timeout=5"
    )


def _get_sorted_sql_files() -> list[str]:
    """
    Get all .sql files from the sql/ directory, sorted by name.

    Sort order: init_database.sql first, then change_*.sql files by numeric suffix.
    """
    sql_files = list(SQL_DIR.glob("*.sql"))

    def migration_key(path: Path) -> tuple[int, int, str]:
        if path.name == "init_database.sql":
            return (0, 0, path.name)
        match = _CHANGE_NUMBER.match(path.name)
        return (
            1,
            int(match.group(1)) if match is not None else 9999,
            path.name,
        )

    sorted_files = sorted(sql_files, key=migration_key)
    return [str(f) for f in sorted_files]


def _execute_sql_file_sync(engine: sa.engine.Engine, file_path: str) -> None:
    """Execute a single .sql file using a sync engine."""
    print(f"\nExecuting: {Path(file_path).name}")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(sql_content))
        print(f"  -> Success: {Path(file_path).name}")
    except Exception as e:
        print(f"  -> Error in {Path(file_path).name}: {e}")
        raise


def _init_postgres() -> None:
    """Initialize PostgreSQL database using SQL files."""
    print("Starting PostgreSQL database schema updates...")
    print(f"SQL directory: {SQL_DIR}")

    engine = sa.create_engine(_build_postgres_url(), echo=False)
    sql_files = _get_sorted_sql_files()

    if not sql_files:
        print("No .sql files found in sql/ folder.")
        return

    print(f"Found {len(sql_files)} SQL files:")
    for f in sql_files:
        print(f"  - {Path(f).name}")

    for file_path in sql_files:
        _execute_sql_file_sync(engine, file_path)

    print("\nAll SQL scripts executed (or skipped if already applied).")
    print("PostgreSQL database schema is up to date.")


def main():
    _init_postgres()
    print("\nDatabase initialization complete.")


if __name__ == "__main__":
    main()
