from __future__ import annotations

import os

from .deepseek_investigation_provider import DeepSeekInvestigationProvider
from .investigation import InvestigationProvider
from .openai_investigation_provider import OpenAIInvestigationProvider


def investigation_provider_from_environment() -> InvestigationProvider:
    provider = os.environ.get("REFLOW_AI_PROVIDER", "deepseek").strip().lower()
    if provider == "deepseek":
        return DeepSeekInvestigationProvider.from_environment()
    if provider == "openai":
        return OpenAIInvestigationProvider.from_environment()
    raise ValueError("REFLOW_AI_PROVIDER must be 'deepseek' or 'openai'")


def investigation_provider_status() -> dict[str, object]:
    provider = os.environ.get("REFLOW_AI_PROVIDER", "deepseek").strip().lower()
    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "configured": bool(os.environ.get("DEEPSEEK_API_KEY")),
            "model": os.environ.get("REFLOW_INVESTIGATION_MODEL", "deepseek-v4-flash"),
        }
    if provider == "openai":
        return {
            "provider": "openai",
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": os.environ.get("REFLOW_INVESTIGATION_MODEL") or None,
        }
    return {"provider": provider, "configured": False, "model": None}


__all__ = ["investigation_provider_from_environment", "investigation_provider_status"]
