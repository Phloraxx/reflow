from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .artifact import verify_benchmark_payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute Gate 11 benchmark reports from exported truth and raw decisions"
    )
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    payload: Any = json.loads(args.artifact.read_text())
    if not isinstance(payload, dict):
        raise SystemExit("benchmark artifact root must be a JSON object")
    reports = verify_benchmark_payload(payload)
    if reports:
        names = ", ".join(report.system_name for report in reports)
        print(f"verified {len(reports)} evaluation reports: {names}")
    else:
        print("verified source-rejected evaluation artifact")


if __name__ == "__main__":
    main()
