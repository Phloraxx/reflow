from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import domain
from .access_auth import (
    AccessAuthBoundary,
    AccessAuthenticationError,
    AccessAuthorizationError,
    AuthenticatedPrincipal,
    auth_boundary_from_env,
)
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
    readiness_probe: Callable[[], None] | None = None,
    auth_boundary: AccessAuthBoundary | None = None,
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
            "authentication": "cloudflare_access" if auth_boundary is not None else "disabled",
        }

    def authenticated_principal(request: Request) -> AuthenticatedPrincipal | None:
        if auth_boundary is None:
            return None
        assertion = request.headers.get("Cf-Access-Jwt-Assertion")
        try:
            return auth_boundary.authenticate(assertion)
        except AccessAuthenticationError as exc:
            raise HTTPException(status_code=401, detail="authentication required") from exc

    def authorized_scope(request: Request, scope_id: str) -> domain.ReconciliationScopeId:
        principal = authenticated_principal(request)
        scope = _scope(scope_id)
        if auth_boundary is None or principal is None:
            return scope
        try:
            auth_boundary.policy.require_scope(principal, scope)
        except AccessAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="forbidden") from exc
        return scope

    def authorize_evaluation(request: Request) -> None:
        principal = authenticated_principal(request)
        if auth_boundary is None or principal is None:
            return
        try:
            auth_boundary.policy.require_evaluation(principal)
        except AccessAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="forbidden") from exc

    @app.get("/api/v1/ready")
    def ready() -> JSONResponse:
        if readiness_probe is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "dependency": "postgresql"},
            )
        try:
            readiness_probe()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "dependency": "postgresql"},
            )
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "dependency": "postgresql"},
        )

    @app.get("/api/v1/scopes/{scope_id}/overview")
    def overview(request: Request, scope_id: str) -> dict[str, object]:
        return asdict(reader.overview(authorized_scope(request, scope_id)))

    @app.get("/api/v1/scopes/{scope_id}/proofs")
    def proofs(request: Request, scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.proofs(authorized_scope(request, scope_id))]

    @app.get("/api/v1/scopes/{scope_id}/proofs/{proof_id}")
    def proof(request: Request, scope_id: str, proof_id: str) -> dict[str, object]:
        return asdict(reader.proof_detail(authorized_scope(request, scope_id), proof_id))

    @app.get("/api/v1/scopes/{scope_id}/exceptions")
    def exceptions(request: Request, scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.exceptions(authorized_scope(request, scope_id))]

    @app.get("/api/v1/scopes/{scope_id}/cases/{case_id}")
    def case_file(request: Request, scope_id: str, case_id: str) -> dict[str, object]:
        return asdict(reader.case_file(authorized_scope(request, scope_id), case_id))

    @app.get("/api/v1/scopes/{scope_id}/sources")
    def sources(request: Request, scope_id: str) -> list[dict[str, object]]:
        return [asdict(item) for item in reader.sources(authorized_scope(request, scope_id))]

    @app.get("/api/v1/evaluation")
    def evaluation(request: Request) -> dict[str, object]:
        authorize_evaluation(request)
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
            normalized = client_path.lstrip("/")
            if normalized == "api" or normalized.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(index_path)

    return app


def app_from_env() -> FastAPI:
    dsn = os.getenv("REFLOW_POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("REFLOW_POSTGRES_DSN is required for the control tower API")
    repo_root = Path(__file__).resolve().parents[2]
    root = Path(
        os.getenv(
            "REFLOW_EVALUATION_ROOT",
            str(repo_root / "data" / "eval" / "gate17"),
        )
    )
    final_summary = Path(
        os.getenv(
            "REFLOW_FINAL_EVALUATION_SUMMARY",
            str(repo_root / "data" / "eval" / "gate19" / "final-summary.json"),
        )
    )
    store = PostgresApplicationStore(dsn)
    service = ReflowApplicationService(store)
    auth_boundary = auth_boundary_from_env()
    web_dist_value = os.getenv("REFLOW_WEB_DIST")
    if web_dist_value is None:
        candidate = Path.cwd() / "web" / "dist"
        web_dist = candidate if candidate.is_dir() else None
    else:
        web_dist = Path(web_dist_value)
    return create_control_tower_app(
        ControlTowerReader(
            service,
            evaluation_root=root,
            final_evaluation_summary=final_summary,
        ),
        web_dist=web_dist,
        readiness_probe=store.check_ready,
        auth_boundary=auth_boundary,
    )
