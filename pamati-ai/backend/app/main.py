import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.audio_routes import router as audio_router
from app.auth_routes import router as auth_router
from app.config import get_settings
from app.conversation_routes import router as conversation_router
from app.dashboard_routes import router as dashboard_router
from app.db import engine
from app.http_security import BodyLimitMiddleware, api_budget
from app.longitudinal_routes import router as longitudinal_router
from app.multimodal_routes import router as multimodal_router
from app.privacy_routes import router as privacy_router
from app.resource_routes import router as resource_router
from app.safety_routes import router as safety_router
from app.visual_routes import router as visual_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine.dispose()


app = FastAPI(title="PamatiAI API", version="0.1.0", lifespan=lifespan,
              dependencies=[Depends(api_budget)])
settings = get_settings()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins,
    allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(resource_router)
app.include_router(privacy_router)
app.include_router(conversation_router)
app.include_router(audio_router)
app.include_router(visual_router)
app.include_router(multimodal_router)
app.include_router(longitudinal_router)
app.include_router(safety_router)
app.include_router(dashboard_router)


@app.middleware("http")
async def private_response_headers(request, call_next):
    request_id = uuid4().hex
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 -- redact the final HTTP/logging boundary
        # Exception messages/tracebacks can contain SQL parameters or submitted text.
        logging.getLogger("pamati.security").error("request_failed id=%s type=%s", request_id, type(exc).__name__)
        response = JSONResponse({"detail": "Service temporarily unavailable"}, status_code=500)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Pydantic's default response echoes rejected passwords, tokens and conversation text.
    return JSONResponse({"detail": "Invalid request"}, status_code=422)


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
