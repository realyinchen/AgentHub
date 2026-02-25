import os
import sqlalchemy as sa
from dotenv import load_dotenv


load_dotenv()

POSTGRE_URL = (
    f"postgresql+psycopg://{os.environ.get('POSTGRES_USER')}:"
    f"{os.environ.get('POSTGRES_PASSWORD')}@"
    f"{os.environ.get('POSTGRES_HOST')}:{os.environ.get('POSTGRES_PORT')}/"
    f"{os.environ.get('POSTGRES_DB')}"
)


SQLs = [
    """
    DROP TABLE IF EXISTS public.agents;

    CREATE TABLE public.agents (
        agent_id VARCHAR(64) PRIMARY KEY,
        description VARCHAR(1024) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    INSERT INTO public.agents (agent_id, description, is_active)
    VALUES ('chatbot', 'A Simple chatbot', true);
    INSERT INTO public.agents (agent_id, description, is_active)
    VALUES ('rag-agent', 'A RAG Agent that can search local knowledge bases and online information.', true);
    """
    """
    DROP TABLE IF EXISTS public.conversations;
    CREATE TABLE public.conversations (
        thread_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title VARCHAR(64) NOT NULL,
        is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX idx_conversations_deleted_updated ON public.conversations (is_deleted, updated_at DESC);
    """
]


def execute_sql_sync():
    engine = sa.create_engine(POSTGRE_URL, echo=False)

    with engine.connect() as conn:
        with conn.begin():
            for sql in SQLs:
                try:
                    sql_clean = "\n".join(
                        line.strip() for line in sql.splitlines() if line.strip()
                    )
                    if sql_clean:
                        conn.execute(sa.text(sql_clean))
                except Exception as e:
                    print(f"Execute {sql} ERROR {e}")


def main():
    execute_sql_sync()


if __name__ == "__main__":
    main()
