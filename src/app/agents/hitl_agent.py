from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool

from app.core.models import llm


@tool
def write_file(filename: str, content: str) -> str:
    """
    Write content to a file.

    Args:
        filename: The path of the file to write.
        content: The content to write into the file.
    """
    print(f"[MOCK] Writing to file {filename} with content:\n{content}")
    return f"Successfully wrote to file {filename} (mock)"


@tool
def execute_sql(query: str) -> str:
    """
    Execute an SQL query (potentially dangerous operation).

    Args:
        query: The SQL query to execute.
    """
    print(f"[MOCK] Executing SQL query: {query}")
    if "SELECT" in query.upper():
        return "Query result: [(1, 'mock_data'), (2, 'another_row')] (mock)"
    elif "DELETE" in query.upper():
        return "Deleted 5 rows (mock, no real operation performed)"
    else:
        return "SQL executed successfully (mock)"


@tool
def read_data(table_name: str) -> str:
    """
    Read data from a table (safe operation).

    Args:
        table_name: The name of the table to read from.
    """
    print(f"[MOCK] Reading data from table {table_name}")
    return f"Data from table {table_name}:\n[{'id': 1, 'name': 'Alice'}, {'id': 2, 'name': 'Bob'}] (mock)"


hitl_agent = create_agent(
    model=llm,
    tools=[write_file, execute_sql, read_data],
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "write_file": True,  # All decisions (approve, edit, reject) allowed
                "execute_sql": {
                    "allowed_decisions": ["approve", "reject"]
                },  # No editing allowed
                # Safe operation, no approval needed
                "read_data": False,
            },
            # Prefix for interrupt messages - combined with tool name and args to form the full message
            # e.g., "Tool execution pending approval: execute_sql with query='DELETE FROM...'"
            # Individual tools can override this by specifying a "description" in their interrupt config
            description_prefix="Tool execution pending approval",
        ),
    ],
)
