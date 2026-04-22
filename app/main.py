from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.routes import router
from app.schemas import error_response
from workflow.runtime.engine import GraphRuntime
from workflow.settings import WorkflowSettings


ROOT = Path(__file__).resolve().parents[1]


def register_exception_handlers(app: FastAPI) -> None:
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

    app = FastAPI(title="OwnCloud Creator Platform", version="0.1.0")
    app.state.root = root
    app.state.settings = settings
    app.state.runtime = runtime
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
