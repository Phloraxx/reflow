from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import domain
from .control_tower import ControlTowerIntegrityError, ControlTowerNotFound, ControlTowerReader
from .persistence import PostgresApplicationStore, ReflowApplicationService

__all__ = ["app_from_env", "create_control_tower_app"]


def _scope(value: str) -> domain.ReconciliationScopeId:
    try:
        return domain.ReconciliationScopeId(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="invalid reconciliation scope id") from exc


def create_control_tower_app(
    reader: ControlTowerReader,
    *,
    web_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="ReFlow Operator Control Tower",
        version="0.1.0",
        description="Read-only Gate 18 projection over immutable ReFlow finance artifacts.",
    )

    @app.exception_handler(ControlTowerNotFound)
    async def not_found(_request: Request, exc: ControlTowerNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ControlTowerIntegrityError)
    async def integrity_error(_request: Request, exc: ControlTowerIntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "error": "control_tower_integrity_error"},
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "read_only",
            "financial_truth_mutation": False,
            "generic_sql": False,
        }

    @app.get("/api/v1/scopes/{scope_id}/overview")
    def overview(scope_id: str) -> dict[str, object]:
        return asdict(reader.overview(_scope(scope_id)))

    @app.get("/api/v1/scopes/{scope_id}/proofs")
    def proofs(scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.proofs(_scope(scope_id))]

    @app.get("/api/v1/scopes/{scope_id}/proofs/{proof_id}")
    def proof(scope_id: str, proof_id: str) -> dict[str, object]:
        return asdict(reader.proof_detail(_scope(scope_id), proof_id))

    @app.get("/api/v1/scopes/{scope_id}/exceptions")
    def exceptions(scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.exceptions(_scope(scope_id))]

    @app.get("/api/v1/scopes/{scope_id}/cases/{case_id}")
    def case_file(scope_id: str, case_id: str) -> dict[str, object]:
        return asdict(reader.case_file(_scope(scope_id), case_id))

    @app.get("/api/v1/scopes/{scope_id}/sources")
    def sources(scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.sources(_scope(scope_id))]

    @app.get("/api/v1/evaluation")
    def evaluation() -> dict[str, object]:
        return asdict(reader.evaluation())

    if web_dist is not None:
        index_path = web_dist / "index.html"
        assets_path = web_dist / "assets"
        if not web_dist.is_dir() or not index_path.is_file():
            raise RuntimeError("control tower web_dist must contain a built index.html")
        if assets_path.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_path), name="control-tower-assets")

        @app.get("/", include_in_schema=False)
        def web_index() -> FileResponse:
            return FileResponse(index_path)

        @app.get("/{client_path:path}", include_in_schema=False)
        def web_client_route(client_path: str) -> FileResponse:
            if client_path == "api" or client_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_path)

    return app


def app_from_env() -> FastAPI:
    dsn = os.getenv("REFLOW_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("REFLOW_POSTGRES_DSN is required for the control tower API")
    root = Path(
        os.getenv(
            "REFLOW_EVALUATION_ROOT",
            str(Path(__file__).resolve().parents[2] / "data" / "eval" / "gate17"),
        )
    )
    store = PostgresApplicationStore(dsn)
    service = ReflowApplicationService(store)
    web_dist_value = os.getenv("REFLOW_WEB_DIST")
    if web_dist_value is None:
        candidate = Path.cwd() / "web" / "dist"
        web_dist = candidate if candidate.is_dir() else None
    else:
        web_dist = Path(web_dist_value)
    return create_control_tower_app(
        ControlTowerReader(service, evaluation_root=root),
        web_dist=web_dist,
    )
