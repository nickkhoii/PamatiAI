from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth_routes import router as auth_router
from app.config import get_settings
from app.db import engine
from app.privacy_routes import router as privacy_router
from app.resource_routes import router as resource_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="PamatiAI API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins,
    allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(resource_router)
app.include_router(privacy_router)


@app.middleware("http")
async def private_response_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class Health(BaseModel):
    status: str
    service: str = "pamati-api"


@app.get("/api/v1/health", response_model=Health, tags=["operations"])
def health() -> Health:
    return Health(status="ok")


@app.get("/api/v1/ready", response_model=Health, responses={503: {"model": Health}}, tags=["operations"])
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content=Health(status="unavailable").model_dump())
    return Health(status="ready")
