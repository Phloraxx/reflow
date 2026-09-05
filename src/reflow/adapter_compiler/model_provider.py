from __future__ import annotations

import os

from .deepseek_provider import DeepSeekAdapterProposalProvider
from .openai_provider import OpenAIAdapterProposalProvider
from .provider import AdapterProposalProvider


def adapter_provider_from_environment() -> AdapterProposalProvider:
    provider = os.environ.get("REFLOW_AI_PROVIDER", "deepseek").strip().lower()
    if provider == "deepseek":
        return DeepSeekAdapterProposalProvider.from_environment()
    if provider == "openai":
        return OpenAIAdapterProposalProvider.from_environment()
    raise ValueError("REFLOW_AI_PROVIDER must be 'deepseek' or 'openai'")


def adapter_provider_status() -> dict[str, object]:
    provider = os.environ.get("REFLOW_AI_PROVIDER", "deepseek").strip().lower()
    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "model": os.environ.get("REFLOW_ADAPTER_MODEL", "deepseek-v4-flash"),
        }
    if provider == "openai":
        return {
            "provider": "openai",
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": os.environ.get("REFLOW_ADAPTER_MODEL") or None,
        }
    return {"provider": provider, "configured": False, "model": None}


__all__ = ["adapter_provider_from_environment", "adapter_provider_status"]
