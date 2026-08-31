from __future__ import annotations

import argparse
import json
from pathlib import Path

from .migration_benchmark_artifact import verify_migration_benchmark_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Gate 12 migration benchmark artifact")
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    report = verify_migration_benchmark_payload(json.loads(args.artifact.read_text()))
    print(
        "verified Gate 12 migration benchmark: "
        f"{report.safe_activations} safe activations, "
        f"{report.unsafe_activations} unsafe activations"
    )


if __name__ == "__main__":
    main()
