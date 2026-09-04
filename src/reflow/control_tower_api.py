from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import domain
from .access_auth import (
    AccessAuthBoundary,
    AccessAuthenticationError,
    AccessAuthorizationError,
    AuthenticatedPrincipal,
    auth_boundary_from_env,
)
from .control_tower import (
    ControlTowerCursorError,
    ControlTowerIntegrityError,
    ControlTowerNotFound,
    ControlTowerReader,
)
from .evaluation.pitch_demo import PitchDatasetConfig, PitchDemoService
from .evaluation.profiles import EvaluationProfile
from .exception_cases import DispositionKind
from .observability import (
    EventSink,
    MetricsRegistry,
    install_http_observability,
    json_event_sink,
    metrics_response,
    metrics_token_from_env,
    normalize_metrics_token,
    request_id,
)
from .operator_audit import (
    OperatorAuditAction,
    OperatorAuditDecision,
    OperatorAuditRecorder,
    PostgresOperatorAuditStore,
    principal_subject_sha256,
)
from .operator_workflow import (
    OperatorCaseWorkflowService,
    OperatorWorkflowConflict,
    OperatorWorkflowError,
    OperatorWorkflowIntegrityError,
)
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
    operator_audit: OperatorAuditRecorder | None = None,
    metrics: MetricsRegistry | None = None,
    metrics_token: str | None = None,
    event_sink: EventSink | None = None,
    case_workflow: OperatorCaseWorkflowService | None = None,
    pitch_demo: PitchDemoService | None = None,
) -> FastAPI:
    if auth_boundary is not None and operator_audit is None:
        raise RuntimeError("authenticated control tower requires operator audit persistence")
    if case_workflow is not None and auth_boundary is None:
        raise RuntimeError("case workflow writes require authenticated control tower mode")
    if pitch_demo is not None and auth_boundary is not None:
        raise RuntimeError("demo mode cannot run behind authenticated production mode")

    metrics_token = normalize_metrics_token(metrics_token)

    app = FastAPI(
        title="ReFlow Operator Control Tower",
        version="0.1.0",
        description=(
            "Gate 18 projection over immutable ReFlow finance artifacts with optional "
            "authenticated exception-workflow dispositions."
        ),
    )
    metrics_registry = metrics if metrics is not None else MetricsRegistry()
    sink = event_sink if event_sink is not None else json_event_sink("reflow-control-tower")
    install_http_observability(app, metrics=metrics_registry, event_sink=sink)

    @app.exception_handler(ControlTowerNotFound)
    async def not_found(_request: Request, exc: ControlTowerNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ControlTowerIntegrityError)
    async def integrity_error(_request: Request, exc: ControlTowerIntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "error": "control_tower_integrity_error"},
        )

    @app.exception_handler(ControlTowerCursorError)
    async def cursor_error(_request: Request, exc: ControlTowerCursorError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "error": "invalid_collection_cursor"},
        )

    @app.exception_handler(OperatorWorkflowConflict)
    async def workflow_conflict(_request: Request, exc: OperatorWorkflowConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "error": "case_workflow_conflict"},
        )

    @app.exception_handler(OperatorWorkflowIntegrityError)
    async def workflow_integrity(
        _request: Request, exc: OperatorWorkflowIntegrityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "error": "case_workflow_integrity_error"},
        )

    @app.exception_handler(OperatorWorkflowError)
    async def workflow_input(_request: Request, exc: OperatorWorkflowError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error": "invalid_case_workflow_command"},
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "mode": "case_workflow" if case_workflow is not None else "read_only",
            "financial_truth_mutation": False,
            "case_workflow_writes": case_workflow is not None,
            "generic_sql": False,
            "authentication": "cloudflare_access" if auth_boundary is not None else "disabled",
            "request_correlation": "generated",
            "operator_audit": "postgresql_append_only"
            if operator_audit is not None
            else "disabled",
            "metrics": "token_gated" if metrics_token is not None else "disabled",
            "demo_mode": pitch_demo is not None,
        }

    def authenticated_principal(request: Request) -> AuthenticatedPrincipal | None:
        if auth_boundary is None:
            return None
        assertion = request.headers.get("Cf-Access-Jwt-Assertion")
        try:
            return auth_boundary.authenticate(assertion)
        except AccessAuthenticationError as exc:
            raise HTTPException(status_code=401, detail="authentication required") from exc

    def audit_access(
        request: Request,
        *,
        principal: AuthenticatedPrincipal,
        action: OperatorAuditAction,
        scope_id: domain.ReconciliationScopeId | None,
        decision: OperatorAuditDecision,
    ) -> None:
        if operator_audit is None:
            return
        try:
            digest = principal_subject_sha256(principal.subject)
            operator_audit.record_access(
                occurred_at=datetime.now(tz=UTC),
                request_id=request_id(request),
                principal_subject_sha256=digest,
                action=action,
                scope_id=scope_id,
                decision=decision,
            )
        except Exception as exc:
            sink(
                {
                    "event.name": "reflow.operator.audit.persistence_failure",
                    "reflow.request_id": request_id(request),
                    "reflow.operator.action": action.value,
                }
            )
            raise HTTPException(status_code=503, detail="operator audit unavailable") from exc
        metrics_registry.record_operator_access(action=action.value, decision=decision.value)
        sink(
            {
                "event.name": "reflow.operator.access",
                "reflow.request_id": request_id(request),
                "reflow.operator.principal_subject_sha256": digest,
                "reflow.operator.action": action.value,
                "reflow.operator.decision": decision.value,
            }
        )

    def authorized_scope(
        request: Request,
        scope_id: str,
        *,
        action: OperatorAuditAction,
    ) -> domain.ReconciliationScopeId:
        principal = authenticated_principal(request)
        scope = _scope(scope_id)
        if auth_boundary is None or principal is None:
            return scope
        try:
            auth_boundary.policy.require_scope(principal, scope)
        except AccessAuthorizationError as exc:
            audit_access(
                request,
                principal=principal,
                action=action,
                scope_id=scope,
                decision=OperatorAuditDecision.DENIED,
            )
            raise HTTPException(status_code=403, detail="forbidden") from exc
        audit_access(
            request,
            principal=principal,
            action=action,
            scope_id=scope,
            decision=OperatorAuditDecision.ALLOWED,
        )
        return scope

    def authorized_case_operator(
        request: Request, scope_id: str
    ) -> tuple[domain.ReconciliationScopeId, AuthenticatedPrincipal]:
        principal = authenticated_principal(request)
        scope = _scope(scope_id)
        if auth_boundary is None or principal is None:
            raise HTTPException(status_code=503, detail="case workflow authorization unavailable")
        action = OperatorAuditAction.APPEND_CASE_DISPOSITION
        try:
            auth_boundary.policy.require_case_operator(principal, scope)
        except AccessAuthorizationError as exc:
            audit_access(
                request,
                principal=principal,
                action=action,
                scope_id=scope,
                decision=OperatorAuditDecision.DENIED,
            )
            raise HTTPException(status_code=403, detail="forbidden") from exc
        audit_access(
            request,
            principal=principal,
            action=action,
            scope_id=scope,
            decision=OperatorAuditDecision.ALLOWED,
        )
        return scope, principal

    def authorize_evaluation(request: Request) -> None:
        principal = authenticated_principal(request)
        if auth_boundary is None or principal is None:
            return
        action = OperatorAuditAction.VIEW_EVALUATION
        try:
            auth_boundary.policy.require_evaluation(principal)
        except AccessAuthorizationError as exc:
            audit_access(
                request,
                principal=principal,
                action=action,
                scope_id=None,
                decision=OperatorAuditDecision.DENIED,
            )
            raise HTTPException(status_code=403, detail="forbidden") from exc
        audit_access(
            request,
            principal=principal,
            action=action,
            scope_id=None,
            decision=OperatorAuditDecision.ALLOWED,
        )

    async def case_disposition_payload(
        request: Request,
    ) -> tuple[int, DispositionKind, str | None, str | None]:
        max_bytes = 8192
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError as exc:
                raise OperatorWorkflowError("request Content-Length is invalid") from exc
            if declared < 0 or declared > max_bytes:
                raise HTTPException(status_code=413, detail="case workflow request too large")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise HTTPException(status_code=413, detail="case workflow request too large")
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OperatorWorkflowError("case workflow request must be valid JSON") from exc
        if not isinstance(payload, Mapping) or any(not isinstance(key, str) for key in payload):
            raise OperatorWorkflowError("case workflow request must be an object")
        keys = set(payload)
        required = {"expected_generation", "kind"}
        allowed = required | {"owner", "note"}
        if not required.issubset(keys) or not keys.issubset(allowed):
            raise OperatorWorkflowError("case workflow request keys are invalid")
        expected_generation = payload.get("expected_generation")
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise OperatorWorkflowError(
                "case workflow expected_generation must be non-negative integer"
            )
        raw_kind = payload.get("kind")
        if not isinstance(raw_kind, str):
            raise OperatorWorkflowError("case workflow disposition kind is invalid")
        try:
            kind = DispositionKind(raw_kind)
        except ValueError as exc:
            raise OperatorWorkflowError("case workflow disposition kind is invalid") from exc
        owner = payload.get("owner")
        note = payload.get("note")
        if owner is not None and not isinstance(owner, str):
            raise OperatorWorkflowError("case workflow owner must be string or null")
        if note is not None and not isinstance(note, str):
            raise OperatorWorkflowError("case workflow note must be string or null")
        return expected_generation, kind, owner, note

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

    @app.get("/internal/metrics", include_in_schema=False)
    def internal_metrics(request: Request) -> PlainTextResponse:
        return metrics_response(request, metrics=metrics_registry, token=metrics_token)

    if pitch_demo is not None:

        @app.get("/api/v1/demo/status")
        def demo_status() -> dict[str, object]:
            return pitch_demo.status()

        @app.post("/api/v1/demo/reset")
        def demo_reset() -> dict[str, object]:
            pitch_demo.reset()
            return pitch_demo.status()

        @app.post("/api/v1/demo/generate")
        async def demo_generate(request: Request) -> dict[str, object]:
            try:
                payload = await request.json()
                if not isinstance(payload, Mapping):
                    raise ValueError("dataset configuration must be an object")
                count = payload.get("settlement_count", 500)
                world_seed = payload.get("world_seed", 402)
                observation_seed = payload.get("observation_seed", 1402)
                profile_value = payload.get(
                    "profile", EvaluationProfile.RECONCILIATION_ADVERSARIAL.value
                )
                if isinstance(count, bool) or not isinstance(count, int):
                    raise ValueError("settlement_count must be integer")
                if isinstance(world_seed, bool) or not isinstance(world_seed, int):
                    raise ValueError("world_seed must be integer")
                if isinstance(observation_seed, bool) or not isinstance(observation_seed, int):
                    raise ValueError("observation_seed must be integer")
                if not isinstance(profile_value, str):
                    raise ValueError("profile must be string")
                config = PitchDatasetConfig(
                    settlement_count=count,
                    profile=EvaluationProfile(profile_value),
                    world_seed=world_seed,
                    observation_seed=observation_seed,
                )
                return pitch_demo.generate(config)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        @app.get("/api/v1/demo/run-stream")
        def demo_run_stream() -> StreamingResponse:
            def events() -> Iterator[str]:
                try:
                    for event in pitch_demo.run_stream():
                        encoded = json.dumps(event, separators=(",", ":"))
                        yield f"data: {encoded}\n\n"
                except RuntimeError as exc:
                    encoded = json.dumps({"event": "error", "detail": str(exc)})
                    yield f"data: {encoded}\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        @app.get("/api/v1/demo/settlements")
        def demo_settlements(status: str | None = None) -> list[dict[str, object]]:
            return pitch_demo.settlements(status=status)

        @app.get("/api/v1/demo/settlements/{settlement_id}")
        def demo_settlement_detail(settlement_id: str) -> dict[str, object]:
            try:
                return pitch_demo.settlement_detail(settlement_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="demo settlement not found") from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.post("/api/v1/demo/unlock-truth")
        def demo_unlock_truth() -> dict[str, object]:
            try:
                return pitch_demo.unlock_truth()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get("/api/v1/demo/razorpay-status")
        def demo_razorpay_status() -> dict[str, object]:
            return pitch_demo.razorpay_status()

        @app.post("/api/v1/demo/razorpay-probe")
        def demo_razorpay_probe() -> dict[str, object]:
            try:
                return pitch_demo.probe_razorpay()
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @app.get("/api/v1/demo/ai-status")
        def demo_ai_status() -> dict[str, object]:
            return pitch_demo.ai_status()

        @app.post("/api/v1/demo/schema-adapter")
        def demo_schema_adapter() -> dict[str, object]:
            try:
                return pitch_demo.propose_bank_schema_adapter()
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/v1/scopes/{scope_id}/overview")
    def overview(request: Request, scope_id: str) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.VIEW_SCOPE_OVERVIEW,
        )
        return asdict(reader.overview(scope))

    @app.get("/api/v1/scopes/{scope_id}/proofs")
    def proofs(request: Request, scope_id: str) -> list[dict[str, object]]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_PROOFS,
        )
        return [asdict(item) for item in reader.proofs(scope)]

    @app.get("/api/v1/scopes/{scope_id}/proofs/page")
    def proofs_page(
        request: Request,
        scope_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_PROOFS,
        )
        page = reader.proofs_page(scope, cursor=cursor, limit=limit)
        return {
            "items": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }

    @app.get("/api/v1/scopes/{scope_id}/proofs/{proof_id}")
    def proof(request: Request, scope_id: str, proof_id: str) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.VIEW_SCOPE_PROOF,
        )
        return asdict(reader.proof_detail(scope, proof_id))

    @app.get("/api/v1/scopes/{scope_id}/exceptions")
    def exceptions(request: Request, scope_id: str) -> list[dict[str, object]]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_EXCEPTIONS,
        )
        return [asdict(item) for item in reader.exceptions(scope)]

    @app.get("/api/v1/scopes/{scope_id}/exceptions/page")
    def exceptions_page(
        request: Request,
        scope_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_EXCEPTIONS,
        )
        page = reader.exceptions_page(scope, cursor=cursor, limit=limit)
        return {
            "items": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }

    @app.get("/api/v1/scopes/{scope_id}/cases/{case_id}")
    def case_file(request: Request, scope_id: str, case_id: str) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.VIEW_SCOPE_CASE,
        )
        return asdict(reader.case_file(scope, case_id))

    if case_workflow is not None:

        @app.post("/api/v1/scopes/{scope_id}/cases/{case_id}/dispositions")
        async def append_case_disposition(
            request: Request, scope_id: str, case_id: str
        ) -> dict[str, object]:
            scope, principal = authorized_case_operator(request, scope_id)
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key is None:
                raise OperatorWorkflowError("Idempotency-Key is required")
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise OperatorWorkflowError("case workflow Content-Type must be application/json")
            expected_generation, kind, owner, note = await case_disposition_payload(request)
            result = case_workflow.append_disposition(
                scope_id=scope,
                case_id=case_id,
                principal_subject=principal.subject,
                idempotency_key=idempotency_key,
                request_id=request_id(request),
                expected_generation=expected_generation,
                kind=kind,
                owner=owner,
                note=note,
            )
            return asdict(result)

    @app.get("/api/v1/scopes/{scope_id}/sources")
    def sources(request: Request, scope_id: str) -> list[dict[str, object]]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_SOURCES,
        )
        return [asdict(item) for item in reader.sources(scope)]

    @app.get("/api/v1/scopes/{scope_id}/sources/page")
    def sources_page(
        request: Request,
        scope_id: str,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, object]:
        scope = authorized_scope(
            request,
            scope_id,
            action=OperatorAuditAction.LIST_SCOPE_SOURCES,
        )
        page = reader.sources_page(scope, cursor=cursor, limit=limit)
        return {
            "items": [asdict(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }

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
    operator_audit = PostgresOperatorAuditStore(dsn) if auth_boundary is not None else None
    metrics_token = metrics_token_from_env()
    web_dist_value = os.getenv("REFLOW_WEB_DIST")
    if web_dist_value is None:
        candidate = Path.cwd() / "web" / "dist"
        web_dist = candidate if candidate.is_dir() else None
    else:
        web_dist = Path(web_dist_value)

    def readiness() -> None:
        store.check_ready()
        if operator_audit is not None:
            operator_audit.check_ready()

    reader = ControlTowerReader(
        service,
        evaluation_root=root,
        final_evaluation_summary=final_summary,
    )
    workflow_mode = os.getenv("REFLOW_CASE_WORKFLOW_WRITES", "disabled")
    if workflow_mode not in {"disabled", "enabled"}:
        raise RuntimeError("REFLOW_CASE_WORKFLOW_WRITES must be 'disabled' or 'enabled'")
    case_workflow = None
    if workflow_mode == "enabled":
        if auth_boundary is None:
            raise RuntimeError("case workflow writes require Cloudflare Access authentication")
        case_workflow = OperatorCaseWorkflowService(reader, service)

    demo_mode = os.getenv("REFLOW_JUDGE_DEMO", "disabled")
    if demo_mode not in {"disabled", "enabled"}:
        raise RuntimeError("REFLOW_JUDGE_DEMO must be 'disabled' or 'enabled'")
    pitch_demo = None
    if demo_mode == "enabled":
        if auth_boundary is not None:
            raise RuntimeError("demo mode requires REFLOW_AUTH_MODE=disabled")
        if case_workflow is not None:
            raise RuntimeError("demo mode cannot enable operator case writes")
        pitch_demo = PitchDemoService()

    return create_control_tower_app(
        reader,
        web_dist=web_dist,
        readiness_probe=readiness,
        auth_boundary=auth_boundary,
        operator_audit=operator_audit,
        metrics_token=metrics_token,
        case_workflow=case_workflow,
        pitch_demo=pitch_demo,
    )
