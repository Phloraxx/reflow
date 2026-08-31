from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .benchmark import benchmark_payload, run_adapter_benchmark
from .benchmark_fixtures import (
    WrongUnitMutationProvider,
    development_adapter_cases,
    development_reference_provider,
)
from .benchmark_verify import verify_adapter_benchmark_payload
from .openai_provider import OpenAIAdapterProposalProvider


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ReFlow Gate 12 adapter benchmark")
    parser.add_argument(
        "--provider",
        choices=("development", "wrong-unit-mutation", "openai"),
        default="development",
    )
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = development_adapter_cases()
    provider_name = args.provider
    model_name: str | None = None
    if args.provider == "development":
        provider = development_reference_provider()
    elif args.provider == "wrong-unit-mutation":
        provider = WrongUnitMutationProvider(
            development_reference_provider(),
            "bench_bank_integer_rupees",
        )
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            parser.error("OPENAI_API_KEY is required for --provider openai")
        if not args.model:
            parser.error("--model is required for --provider openai")
        provider = OpenAIAdapterProposalProvider(api_key=api_key, model=args.model)
        model_name = args.model

    results, report = run_adapter_benchmark(provider, cases)
    payload = benchmark_payload(
        cases,
        results,
        report,
        provider_name=provider_name,
        model_name=model_name,
    )
    verify_adapter_benchmark_payload(payload)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered)


if __name__ == "__main__":
    main()
