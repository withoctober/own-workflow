from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routes import router
from app.schemas import error_response
from workflow.runtime.engine import GraphRuntime
from workflow.runtime.scheduler import TenantFlowScheduler
from workflow.settings import WorkflowSettings


ROOT = Path(__file__).resolve().parents[1]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=error_response(code=exc.status_code, message=str(exc.detail), data=""),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=error_response(code=exc.status_code, message=str(exc.detail), data=""),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=error_response(code=422, message="validation error", data=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=200,
            content=error_response(code=500, message=str(exc) or "internal server error", data=""),
        )


def create_app(root: Path = ROOT) -> FastAPI:
    settings = WorkflowSettings.from_root(root)
    runtime = GraphRuntime(settings)
    scheduler = TenantFlowScheduler(
        settings,
        runtime,
        poll_interval_seconds=settings.schedule_poll_interval_seconds,
        stale_lock_seconds=settings.schedule_stale_lock_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.scheduler = scheduler
        scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title="OwnCloud Creator Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.root = root
    app.state.settings = settings
    app.state.runtime = runtime
    app.state.scheduler = scheduler
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    return app


app = create_app()
