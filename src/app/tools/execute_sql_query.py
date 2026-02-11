import io
import csv
import logging
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional

from langchain_core.tools import tool
from sqlalchemy import text, inspect
from sqlalchemy.exc import SQLAlchemyError

from app.database import adb_manager

logger = logging.getLogger(__name__)


@tool
async def execute_sql_query(
    sql: str,
    max_rows: int = 500,
    max_chars: int = 15000,
) -> str:
    """
    Execute a read-only SQL SELECT query against the PostgreSQL database.
    Returns results as semicolon-separated CSV string.

    Safety features:
    - Only SELECT statements allowed
    - Blocks dangerous keywords (DROP, DELETE, UPDATE, etc.)
    - Truncates large result sets (>500 rows or >15k chars)

    Args:
        sql: The SQL query to execute (must be a SELECT statement)
        max_rows: Maximum rows to return (default: 500)
        max_chars: Maximum characters in output (default: 15000)

    Returns:
        CSV-formatted string or error message
    """
    if not sql or not isinstance(sql, str):
        return "Error: Invalid or empty SQL query provided."

    sql_lower = sql.lower().strip()

    # Security checks
    if not sql_lower.startswith("select"):
        return "Error: Only SELECT queries are allowed for security reasons."

    dangerous_keywords = {
        "drop",
        "delete",
        "update",
        "insert",
        "alter",
        "truncate",
        "create",
        "grant",
        "revoke",
        "comment",
        "--",
        "/*",
        "xp_",
        "exec",
        "sp_",
    }
    if any(keyword in sql_lower for keyword in dangerous_keywords):
        return "Error: Query contains potentially harmful or disallowed operations."

    try:
        async with adb_manager.session() as session:
            result = await session.execute(text(sql))
            rows = result.fetchall()

            if not result.keys() and not rows:
                return ""

            # Column names
            colnames = list(result.keys()) if result.keys() else []
            if not colnames and rows:
                num_cols = len(rows[0]) if rows else 0
                colnames = (
                    [f"col_{i + 1}" for i in range(num_cols)]
                    if num_cols > 1
                    else ["result"]
                )

            # Build CSV
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";")

            writer.writerow(colnames)

            warning = None
            row_count = len(rows)
            for i, row in enumerate(rows):
                if i >= max_rows:
                    warning = (
                        f"# Warning: Query returned {row_count} rows, "
                        f"truncated to {max_rows} rows."
                    )
                    break
                writer.writerow([_to_csv_string_value(v) for v in row])

            csv_str = output.getvalue().rstrip("\n")  # Clean trailing newline

            if warning:
                csv_str += "\n" + warning

            # Character limit
            if len(csv_str) > max_chars:
                truncated = csv_str[: max_chars - 100]
                last_nl = truncated.rfind("\n")
                if last_nl != -1:
                    truncated = truncated[: last_nl + 1]
                csv_str = (
                    truncated
                    + f"\n# Error: Result too large. Truncated to ~{max_chars} chars."
                )

            return csv_str

    except SQLAlchemyError as e:
        # Log sanitized SQL (first 200 chars)
        safe_sql = sql[:200] + "..." if len(sql) > 200 else sql
        logger.error(f"SQL execution failed: {e} | Query: {safe_sql}")
        return f"Database error: {str(e).replace('\n', ' ').strip()}"

    except Exception as e:
        logger.exception("Unexpected error in SQL query execution")
        return f"Unexpected error: {str(e)}"


@tool
async def get_table_schema(
    table_names: Optional[List[str]] = None,
    include_all: bool = False,
) -> str:
    """
    Retrieve schema information (column names and types) for one or more tables in the PostgreSQL database.

    This tool is useful for understanding the database structure before writing SQL queries.
    It returns a human-readable formatted string listing tables and their columns.

    Args:
        table_names: Optional list of specific table names to fetch schema for.
                     If None and include_all=False, returns an error or empty info.
        include_all: If True, fetches schema for ALL tables in the database (overrides table_names).

    Returns:
        Formatted string with table schema information, or an error message if something fails.
    """
    try:
        async with adb_manager.session() as session:
            insp = inspect(session.bind)

            # Determine which tables to inspect
            if include_all:
                tables = await insp.get_table_names()
                logger.debug(f"Fetching schema for all {len(tables)} tables")
            elif table_names:
                all_tables = await insp.get_table_names()
                tables = [t for t in table_names if t in all_tables]
                if len(tables) < len(table_names):
                    missing = set(table_names) - set(tables)
                    logger.warning(f"Some requested tables not found: {missing}")
            else:
                return "Error: Please specify table_names or set include_all=True."

            if not tables:
                return "No matching tables found in the database."

            schema_parts = []
            for table in tables:
                try:
                    columns = await insp.get_columns(table)
                    if not columns:
                        schema_parts.append(
                            f"Table: {table}\n  (no columns or access denied)"
                        )
                        continue

                    col_lines = []
                    for col in columns:
                        col_type = str(col["type"])
                        nullable = "NULL" if col["nullable"] else "NOT NULL"
                        col_lines.append(f"  - {col['name']}: {col_type} {nullable}")

                    schema_parts.append(f"Table: {table}\n" + "\n".join(col_lines))

                except Exception as e:
                    logger.warning(f"Failed to inspect table {table}: {e}")
                    schema_parts.append(f"Table: {table}\n  (error retrieving schema)")

            if not schema_parts:
                return "No schema information could be retrieved."

            return "\n\n".join(schema_parts)

    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching schema: {e}")
        return f"Database error: {str(e).replace('\n', ' ').strip()}"

    except Exception as e:
        logger.exception("Unexpected error while fetching table schema")
        return f"Unexpected error: {str(e)}"


def _to_csv_string_value(obj: Any) -> str:
    """
    Safely convert any value to a CSV-compatible string.
    Handles common types, falls back to JSON for complex objects.
    """
    if obj is None:
        return ""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(float(obj))
    if isinstance(obj, (list, dict)):
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            return str(obj)
    return str(obj)
