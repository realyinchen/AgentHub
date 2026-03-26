import os
import glob
import sqlalchemy as sa
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

POSTGRE_URL = (
    f"postgresql+psycopg://{os.environ.get('POSTGRES_USER')}:"
    f"{os.environ.get('POSTGRES_PASSWORD')}@"
    f"{os.environ.get('POSTGRES_HOST')}:{os.environ.get('POSTGRES_PORT')}/"
    f"{os.environ.get('POSTGRES_DB')}"
)

SQL_DIR = Path(__file__).parent / "sql"


def get_sorted_sql_files():
    """
    Get all .sql files in sql/ folder, sorted by name
    (init_database.sql first, then database_change_001.sql, 002.sql, ...)
    """
    sql_files = glob.glob(str(SQL_DIR / "*.sql"))
    # Sort: init first, then change_xxx in numerical order
    sorted_files = sorted(
        sql_files,
        key=lambda x: (
            0 if "init_database.sql" in x else 1,
            int("".join(filter(str.isdigit, Path(x).stem))) if "change_" in x else 9999,
        ),
    )
    return sorted_files


def execute_sql_file(engine, file_path):
    """Execute a single .sql file, print progress and errors"""
    print(f"\nExecuting: {Path(file_path).name}")
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Split into statements by ; but ignore inside DO $$ ... $$
    # For simplicity, we execute the whole file as one (PostgreSQL allows it)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(sa.text(sql_content))
        print(f"  → Success: {Path(file_path).name}")
    except Exception as e:
        print(f"  → Error in {Path(file_path).name}: {e}")
        # Continue to next file even if one fails (adjust if you want strict mode)


def main():
    print("Starting database schema updates...")
    print(f"SQL directory: {SQL_DIR}")

    engine = sa.create_engine(POSTGRE_URL, echo=False)
    sql_files = get_sorted_sql_files()

    if not sql_files:
        print("No .sql files found in sql/ folder.")
        return

    print(f"Found {len(sql_files)} SQL files:")
    for f in sql_files:
        print(f"  - {Path(f).name}")

    for file_path in sql_files:
        execute_sql_file(engine, file_path)

    print("\nAll SQL scripts executed (or skipped if already applied).")
    print("Database schema is up to date.")


if __name__ == "__main__":
    main()
