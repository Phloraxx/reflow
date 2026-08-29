from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def _json_default(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"unsupported source payload value {type(value).__name__}")


def source_payload_sha256(payload: Mapping[str, object]) -> str:
    """Hash deterministic JSON source evidence using the repository's canonical encoding."""
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_envelope_id_value(
    source_kind: str,
    source_record_id: str,
    payload_sha256: str,
) -> str:
    """Derive the stable raw-evidence ID from source identity and immutable payload digest."""
    material = f"{source_kind}\0{source_record_id}\0{payload_sha256}".encode()
    return f"src_{hashlib.sha256(material).hexdigest()[:24]}"
