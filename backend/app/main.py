from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.routes import auth, health, leads
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.core.middleware import MaxBodySizeMiddleware
from app.core.csrf import OriginCheckMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    application = FastAPI(
        title="6thSense API",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.state.limiter = limiter

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(MaxBodySizeMiddleware)
    application.add_middleware(OriginCheckMiddleware)

    @application.exception_handler(RequestValidationError)
    async def _validation_handler(_req: Request, exc: RequestValidationError):
        errors: dict[str, str] = {}
        for err in exc.errors():
            loc = err.get("loc") or ()
            field = loc[-1] if loc else "body"
            errors[str(field)] = err.get("msg", "Invalid value.")
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errors": errors},
        )

    @application.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(_req: Request, _exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Too many requests. Please slow down."},
        )

    application.include_router(health.router)
    application.include_router(leads.router)
    application.include_router(auth.router)
    return application


app = create_app()
