# pyright: reportArgumentType=false

from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings

from app.core.config import settings


embedding_model = DashScopeEmbeddings(
    model=settings.EMBEDDING_MODEL_NAME,
    dashscope_api_key=settings.COMPATIBLE_API_KEY.get_secret_value(), # type: ignore
)


llm = ChatOpenAI(
    model=settings.LLM_NAME,
    temperature=0,
    base_url=settings.COMPATIBLE_BASE_URL,
    api_key=settings.COMPATIBLE_API_KEY,
)
