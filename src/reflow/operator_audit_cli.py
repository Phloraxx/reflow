from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from typing import Protocol

from .operator_audit import OperatorAccessAudit, PostgresOperatorAuditStore


class AuditReader(Protocol):
    def check_ready(self) -> None: ...

    def list_recent(self, *, limit: int = 50) -> tuple[OperatorAccessAudit, ...]: ...


StoreFactory = Callable[[str], AuditReader]


def _readonly_store(dsn: str) -> AuditReader:
    return PostgresOperatorAuditStore(dsn, initialize=False)


def _payload(event: OperatorAccessAudit) -> dict[str, object]:
    return {
        "audit_id": event.audit_id,
        "occurred_at": event.occurred_at.isoformat(),
        "request_id": event.request_id,
        "principal_subject_sha256": event.principal_subject_sha256,
        "action": event.action.value,
        "scope_id": None if event.scope_id is None else str(event.scope_id),
        "decision": event.decision.value,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    store_factory: StoreFactory = _readonly_store,
) -> int:
    parser = argparse.ArgumentParser(description="Read recent ReFlow operator access audit records")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    dsn = os.getenv("REFLOW_POSTGRES_DSN")
    if dsn is None or not dsn or dsn != dsn.strip():
        raise RuntimeError("REFLOW_POSTGRES_DSN is required for operator audit inspection")
    store = store_factory(dsn)
    store.check_ready()
    events = store.list_recent(limit=args.limit)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "count": len(events),
                "events": [_payload(event) for event in events],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
