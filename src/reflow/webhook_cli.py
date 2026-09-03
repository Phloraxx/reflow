from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime

from .persistence import PostgresApplicationStore
from .webhook_ingress import RazorpayWebhookIngress, razorpay_webhook_ingress_from_env


def _ingress_from_env() -> RazorpayWebhookIngress:
    dsn = os.getenv("REFLOW_POSTGRES_DSN")
    if dsn is None or not dsn.strip() or dsn != dsn.strip():
        raise RuntimeError("REFLOW_POSTGRES_DSN is required")
    application_store = PostgresApplicationStore(dsn)
    ingress, _readiness = razorpay_webhook_ingress_from_env(
        dsn=dsn,
        journal=application_store,
    )
    if ingress is None:
        raise RuntimeError("REFLOW_RAZORPAY_WEBHOOK_MODE=enabled is required")
    return ingress


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or replay retained Razorpay webhook receipts"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="list bounded receipt metadata")
    listing.add_argument("--limit", type=int, default=50)
    attempts = sub.add_parser("attempts", help="show processing attempts for one receipt")
    attempts.add_argument("event_id")
    replay = sub.add_parser("replay", help="replay one immutable retained receipt")
    replay.add_argument("event_id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    ingress = _ingress_from_env()
    if args.command == "list":
        payload = [asdict(item) for item in ingress.list_receipts(limit=args.limit)]
    elif args.command == "attempts":
        payload = [asdict(item) for item in ingress.receipt_attempts(args.event_id)]
    else:
        payload = asdict(
            ingress.replay(
                args.event_id,
                attempted_at=datetime.now(tz=UTC),
            )
        )
    print(json.dumps(payload, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
