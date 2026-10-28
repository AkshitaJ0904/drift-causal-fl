
from fastapi import FastAPI

from api.health import router as health_router
from api.ingestion import router as ingestion_router
from core.config import get_settings
from core.middleware import RequestBodyLimitMiddleware

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Security platform for federated-learning model updates.",
)

app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_size=10_000_000,
)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(ingestion_router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running"}
