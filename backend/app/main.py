import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import Base, add_missing_columns, engine
from app.project_media import media_dir
from app.routers import admin, auth, broker, dev, hod, settings as settings_router, webhooks
from app.salesforce.base import SalesforceError, SalesforceNotConnected

log = logging.getLogger("broker_app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.check_production_ready()
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
        add_missing_columns()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.test_login_codes_in_log:
        logging.getLogger("broker_app").warning(
            "TEST_LOGIN_CODES_IN_LOG is on: mobile login codes are written to this log while SMS isn't set up. "
            "Turn it off before real brokers use the app."
        )
    app = FastAPI(
        title="Ambuja Neotia Partner API",
        description="Backend for the Channel Partner mobile app and the admin portal. Talks to Salesforce.",
        version="1.0.0",
        lifespan=lifespan,
        # Interactive docs only outside production.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Errors go out as { "message": "..." }, which both apps already display.
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse({"message": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = next((str(p) for p in reversed(first.get("loc", ())) if isinstance(p, str) and p != "body"), "")
        message = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        return JSONResponse({"message": f"{field}: {message}" if field else message}, status_code=422)

    @app.exception_handler(SalesforceError)
    async def salesforce_error(_: Request, exc: SalesforceError):
        log.error("Salesforce error: %s", exc)
        return JSONResponse({"message": "Salesforce is not responding. Please try again shortly."}, status_code=502)

    @app.exception_handler(SalesforceNotConnected)
    async def salesforce_not_connected(_: Request, exc: SalesforceNotConnected):
        log.warning("%s", exc)
        return JSONResponse({"message": "This isn't connected to Salesforce yet. Please try again later."}, status_code=503)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        # Someone opening the bare address (e.g. checking the tunnel link) sees it's up, not a 404.
        return {"service": "Ambuja Neotia Broker App API", "status": "ok"}

    app.include_router(auth.router)
    app.include_router(broker.router)
    app.include_router(admin.router)
    app.include_router(settings_router.router)
    app.include_router(hod.router)
    app.include_router(webhooks.router)
    if settings.salesforce_mode == "mock" and settings.environment != "production":
        app.include_router(dev.router)
    # Admin-uploaded project images (unguessable names). Public, so <Image> in the app needs no token.
    app.mount("/media", StaticFiles(directory=media_dir()), name="media")
    return app


app = create_app()
