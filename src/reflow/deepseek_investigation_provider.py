from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .investigation import (
    InvestigationContext,
    InvestigationProvider,
    ReadOnlyInvestigationTools,
)
from .openai_investigation_provider import (
    _INSTRUCTIONS,
    JsonTransport,
    OpenAIInvestigationError,
    _context_input,
    _default_transport,
    _model_tool_output,
    _output_items,
    _proposal_schema,
)
from .openai_transport_security import (
    validate_openai_https_endpoint,
    validate_openai_timeout_seconds,
)


def _deepseek_output_text(response: Mapping[str, object]) -> str:
    texts: list[str] = []
    for item in _output_items(response):
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise OpenAIInvestigationError("DeepSeek message content must be an array")
        for part in content:
            if not isinstance(part, Mapping):
                continue
            if part.get("type") == "refusal":
                raise OpenAIInvestigationError("DeepSeek investigation model refused")
            if part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
    if not texts:
        raise OpenAIInvestigationError("DeepSeek response contains no final output_text")
    return "".join(texts)


@dataclass(frozen=True, slots=True)
class DeepSeekInvestigationProvider(InvestigationProvider):
    api_key: str
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com/responses"
    timeout_seconds: float = 30.0
    transport: JsonTransport = _default_transport

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("DeepSeek API key cannot be empty")
        if not self.model or self.model != self.model.strip():
            raise ValueError("DeepSeek model must be non-empty and trimmed")
        validate_openai_https_endpoint(self.base_url)
        validate_openai_timeout_seconds(self.timeout_seconds)

    @classmethod
    def from_environment(cls, *, model: str | None = None) -> DeepSeekInvestigationProvider:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        selected = model or os.environ.get("REFLOW_INVESTIGATION_MODEL", "deepseek-v4-flash")
        return cls(api_key=api_key, model=selected)

    def _request(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        try:
            response = self.transport(
                self.base_url,
                {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                payload,
                self.timeout_seconds,
            )
        except OpenAIInvestigationError:
            raise
        except Exception as exc:
            raise OpenAIInvestigationError(
                f"DeepSeek investigation transport failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(response, Mapping):
            raise OpenAIInvestigationError("DeepSeek transport response must be an object")
        if response.get("error") is not None:
            raise OpenAIInvestigationError("DeepSeek response reported an error")
        status = response.get("status")
        if status is not None and status != "completed":
            details = response.get("incomplete_details")
            reason = details.get("reason") if isinstance(details, Mapping) else None
            raise OpenAIInvestigationError(
                f"DeepSeek response did not complete: status={status!r} reason={reason!r}"
            )
        return response

    def propose(
        self,
        context: InvestigationContext,
        tools: ReadOnlyInvestigationTools,
    ) -> Mapping[str, object]:
        case_view = tools.case_snapshot()
        proof_view = tools.proof_snapshot()
        source_views = [
            tools.source_evidence(source_id) for source_id in context.available_source_envelope_ids
        ]
        evidence_packet = {
            "context": json.loads(_context_input(context)),
            "case_snapshot": _model_tool_output(case_view),
            "proof_snapshot": _model_tool_output(proof_view),
            "source_evidence": [_model_tool_output(item) for item in source_views],
        }
        payload: dict[str, object] = {
            "model": self.model,
            "reasoning": {"effort": "none"},
            "max_output_tokens": 1800,
            "instructions": (
                _INSTRUCTIONS
                + "\nReFlow has already gathered the complete bounded read-only evidence packet. "
                "Do not request tools. Return only the final structured recommendation. "
                "Citations must be unique and lexicographically sorted. Financial claims "
                "must contain at most one claim per fact and be sorted lexicographically by "
                "fact; use an empty financial_claims array unless a numeric claim is needed. "
                "Hypothesis must be one concise sentence under three hundred characters and "
                "contain no digits. Never restate the same financial "
                "fact under multiple claim entries. If financial_status is pending_bank_credit "
                "and the bank source is waiting, late, or partial, prefer REQUEST_SOURCE with "
                "request_source_kind bank when the evidence supports it. For residual or "
                "contradicted cases, prefer REQUEST_HUMAN_REVIEW when evidence supports review. "
                "If and only if you choose ABSTAIN, hypothesis and request_source_kind must be "
                "null and citations and financial_claims must both be empty arrays."
            ),
            "input": json.dumps(
                evidence_packet,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "reflow_investigation_proposal",
                    "schema": _proposal_schema(),
                }
            },
        }
        response = self._request(payload)
        try:
            decoded: Any = json.loads(_deepseek_output_text(response))
        except json.JSONDecodeError as exc:
            raise OpenAIInvestigationError(
                "DeepSeek structured investigation output is not valid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise OpenAIInvestigationError(
                "DeepSeek structured investigation output must be one object"
            )
        return decoded


__all__ = ["DeepSeekInvestigationProvider"]
