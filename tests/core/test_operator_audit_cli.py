from __future__ import annotations

import json
from datetime import UTC, datetime

from reflow.domain import ReconciliationScopeId
from reflow.operator_audit import (
    OperatorAccessAudit,
    OperatorAuditAction,
    OperatorAuditDecision,
    principal_subject_sha256,
)
from reflow.operator_audit_cli import main

NOW = datetime(2026, 9, 3, 18, 30, tzinfo=UTC)


def test_operator_audit_cli_outputs_only_pseudonymous_bounded_records(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "REFLOW_POSTGRES_DSN",
        "postgresql://secret-user:secret-pass@example.invalid/private",
    )
    event = OperatorAccessAudit(
        audit_id=7,
        occurred_at=NOW,
        request_id="e" * 32,
        principal_subject_sha256=principal_subject_sha256("cf-subject-cli"),
        action=OperatorAuditAction.VIEW_SCOPE_OVERVIEW,
        scope_id=ReconciliationScopeId("scope_cli_audit"),
        decision=OperatorAuditDecision.ALLOWED,
    )

    class StubStore:
        def check_ready(self) -> None:
            return None

        def list_recent(self, *, limit: int = 50) -> tuple[OperatorAccessAudit, ...]:
            assert limit == 1
            return (event,)

    seen_dsn: list[str] = []

    def factory(dsn: str) -> StubStore:
        seen_dsn.append(dsn)
        return StubStore()

    assert main(["--limit", "1"], store_factory=factory) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["events"][0]["action"] == "view_scope_overview"
    assert payload["events"][0]["scope_id"] == "scope_cli_audit"
    rendered = json.dumps(payload, sort_keys=True)
    assert "secret-pass" not in rendered
    assert "example.invalid" not in rendered
    assert "cf-subject-cli" not in rendered
    assert seen_dsn == ["postgresql://secret-user:secret-pass@example.invalid/private"]
