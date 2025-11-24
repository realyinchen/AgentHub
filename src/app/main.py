from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import settings
from app.api.routes import api_router


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


app = FastAPI(generate_unique_id_function=custom_generate_unique_id)
app.include_router(api_router, prefix=settings.API_V1_STR)
