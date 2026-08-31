from __future__ import annotations

import argparse
import json
from pathlib import Path

from .migration_benchmark import run_migration_benchmark
from .migration_benchmark_artifact import (
    migration_benchmark_payload,
    verify_migration_benchmark_payload,
)
from .migration_benchmark_fixtures import development_migration_cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ReFlow Gate 12 migration benchmark")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = development_migration_cases()
    results, report = run_migration_benchmark(cases)
    payload = migration_benchmark_payload(cases, results, report)
    verify_migration_benchmark_payload(payload)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
