from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark_verify import verify_adapter_benchmark_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a ReFlow Gate 12 adapter artifact")
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    report = verify_adapter_benchmark_payload(json.loads(args.artifact.read_text()))
    print(
        "verified adapter benchmark: "
        f"{report.case_count} cases, {report.unsafe_activations} unsafe activations"
    )


if __name__ == "__main__":
    main()
