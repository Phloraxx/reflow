from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reflow.bank_proof import prove_all_bank_receipts
from reflow.ingestion import AdapterError, ingest_observed_batch
from reflow.journal import InMemoryJournal, JournalConflictError
from reflow.money_graph import build_money_graph
from reflow.reconciliation_proof import InMemoryProofLedger, ReconciliationStatus
from reflow.settlement_proof import prove_all_settlement_compositions
from reflow.simulator import WorldConfig, generate_world, observe_world

from .profiles import EvaluationProfile, corruption_plan

SCALE_BENCHMARK_SCHEMA_VERSION = "gate17-scale-benchmark-v1"
DEFAULT_RECEIVED_AT = datetime(2027, 1, 1, tzinfo=UTC)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _artifact_digest(payload: dict[str, Any]) -> str:
    material = dict(payload)
    material.pop("artifact_sha256", None)
    return hashlib.sha256(_canonical_bytes(material)).hexdigest()


def verify_scale_benchmark_payload(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ValueError("scale benchmark artifact root must be an object")
    if payload.get("schema_version") != SCALE_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("scale benchmark schema version mismatch")
    digest = payload.get("artifact_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("scale benchmark artifact digest is invalid")
    if digest != _artifact_digest(payload):
        raise ValueError("scale benchmark artifact digest does not match payload")
    config = payload.get("config")
    hardware = payload.get("hardware")
    metrics = payload.get("metrics")
    if (
        not isinstance(config, dict)
        or not isinstance(hardware, dict)
        or not isinstance(metrics, dict)
    ):
        raise ValueError("scale benchmark artifact sections are invalid")
    if config.get("worker_count") != 1:
        raise ValueError("Gate 17 benchmark must disclose one-process execution")
    if config.get("database_mode") != "in_memory_core":
        raise ValueError("Gate 17 core benchmark database mode is invalid")


def _observed_row_count(observed: object) -> int:
    required = (
        "merchant_rows",
        "razorpay_events",
        "recon_rows",
        "settlement_rows",
        "bank_rows",
    )
    total = 0
    for name in required:
        rows = getattr(observed, name, None)
        if not isinstance(rows, tuple):
            raise TypeError(f"observed benchmark source {name} must be tuple")
        total += len(rows)
    return total


def run_scale_benchmark(
    *,
    settlement_count: int,
    profile: EvaluationProfile,
    world_seed: int = 401,
    observation_seed: int = 1401,
    received_at: datetime = DEFAULT_RECEIVED_AT,
) -> dict[str, Any]:
    if isinstance(settlement_count, bool) or not isinstance(settlement_count, int):
        raise TypeError("settlement_count must be int")
    if settlement_count < 1:
        raise ValueError("settlement_count must be positive")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")

    started = time.perf_counter()
    world = generate_world(world_seed, WorldConfig(settlement_count=settlement_count))
    generated = time.perf_counter()
    bundle = observe_world(
        world,
        seed=observation_seed,
        plan=corruption_plan(profile),
    )
    observed_at = time.perf_counter()
    raw_rows = _observed_row_count(bundle.observed)
    journal = InMemoryJournal()

    source_rejection: dict[str, object] | None = None
    proof_count = 0
    status_counts = {status.value: 0 for status in ReconciliationStatus}
    graph_edge_count = 0
    ingestion_done = observed_at
    graph_done = observed_at
    composition_done = observed_at
    bank_done = observed_at
    proof_done = observed_at

    try:
        batch = ingest_observed_batch(bundle.observed, journal, received_at=received_at)
        ingestion_done = time.perf_counter()
        graph = build_money_graph(batch)
        graph_done = time.perf_counter()
        graph_edge_count = len(graph.edges)
        compositions = prove_all_settlement_compositions(batch, graph)
        composition_done = time.perf_counter()
        banks = prove_all_bank_receipts(batch)
        bank_done = time.perf_counter()
        ledger = InMemoryProofLedger()
        update = ledger.apply_batch(
            batch,
            journal,
            compositions,
            banks,
            knowledge_cutoff=received_at,
            generated_at=received_at + timedelta(microseconds=1),
        )
        proof_done = time.perf_counter()
        proof_count = len(update.created_versions)
        for proof in update.created_versions:
            status_counts[proof.status.value] += 1
    except (AdapterError, JournalConflictError) as exc:
        proof_done = time.perf_counter()
        source_rejection = {
            "error_type": type(exc).__name__,
            "message": str(exc),
        }

    total_seconds = proof_done - started
    ingestion_seconds = ingestion_done - observed_at
    composition_seconds = composition_done - graph_done
    proof_pipeline_seconds = proof_done - ingestion_done
    exception_count = proof_count - status_counts[ReconciliationStatus.PROVEN_RECONCILED.value]
    metrics: dict[str, object] = {
        "raw_rows": raw_rows,
        "journal_entries": len(journal),
        "world_payment_events": world.transaction_count,
        "world_recon_entries": world.recon_count,
        "graph_edges": graph_edge_count,
        "proof_count": proof_count,
        "exception_count": exception_count,
        "seconds_generate": round(generated - started, 6),
        "seconds_observe": round(observed_at - generated, 6),
        "seconds_ingest": round(ingestion_seconds, 6),
        "seconds_graph": round(graph_done - ingestion_done, 6),
        "seconds_composition": round(composition_seconds, 6),
        "seconds_bank": round(bank_done - composition_done, 6),
        "seconds_proof_ledger": round(proof_done - bank_done, 6),
        "seconds_proof_pipeline": round(proof_pipeline_seconds, 6),
        "seconds_total": round(total_seconds, 6),
        "rows_per_second_ingest": (
            None if ingestion_seconds <= 0 else round(raw_rows / ingestion_seconds, 2)
        ),
        "settlements_per_second_proof_pipeline": (
            None if proof_pipeline_seconds <= 0 else round(proof_count / proof_pipeline_seconds, 2)
        ),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    payload: dict[str, Any] = {
        "schema_version": SCALE_BENCHMARK_SCHEMA_VERSION,
        "status": "source_rejected" if source_rejection is not None else "evaluated",
        "config": {
            "settlement_count": settlement_count,
            "profile": profile.value,
            "world_seed": world_seed,
            "observation_seed": observation_seed,
            "received_at": received_at.isoformat(),
            "database_mode": "in_memory_core",
            "worker_count": 1,
        },
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
        },
        "metrics": metrics,
        "status_counts": status_counts,
        "source_rejection": source_rejection,
        "artifact_sha256": "",
    }
    payload["artifact_sha256"] = _artifact_digest(payload)
    verify_scale_benchmark_payload(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or verify one ReFlow Gate 17 scale case")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--settlements", type=int)
    mode.add_argument("--verify", type=Path)
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in EvaluationProfile],
        default=EvaluationProfile.CLEAN.value,
    )
    parser.add_argument("--world-seed", type=int, default=401)
    parser.add_argument("--observation-seed", type=int, default=1401)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        payload: object = json.loads(args.verify.read_text())
        verify_scale_benchmark_payload(payload)
        print(json.dumps({"status": "verified", "artifact": str(args.verify)}, sort_keys=True))
        return
    assert args.settlements is not None
    payload = run_scale_benchmark(
        settlement_count=args.settlements,
        profile=EvaluationProfile(args.profile),
        world_seed=args.world_seed,
        observation_seed=args.observation_seed,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
