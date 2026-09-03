from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

import jwt

from .domain import ReconciliationScopeId

MAX_ACCESS_TOKEN_BYTES = 16 * 1024
MAX_JWKS_RESPONSE_BYTES = 512 * 1024
MAX_JWKS_TIMEOUT_SECONDS = 30.0
DEFAULT_JWKS_TIMEOUT_SECONDS = 5.0
DEFAULT_JWKS_CACHE_SECONDS = 300.0
MAX_POLICY_BYTES = 1024 * 1024


class AccessAuthenticationError(ValueError):
    """Cloudflare Access identity could not be cryptographically established."""


class AccessAuthorizationError(ValueError):
    """An authenticated principal is not authorized for the requested resource."""


class ControlTowerRole(StrEnum):
    SCOPE_VIEWER = "scope_viewer"
    EVALUATION_REVIEWER = "evaluation_reviewer"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    subject: str
    email: str


@dataclass(frozen=True, slots=True)
class PrincipalGrant:
    email: str
    roles: frozenset[ControlTowerRole]
    scopes: frozenset[ReconciliationScopeId]


def _normalized_email(value: object) -> str:
    if not isinstance(value, str):
        raise AccessAuthorizationError("authorization principal email is invalid")
    email = value.strip().lower()
    if value != value.strip() or not email or len(email) > 320:
        raise AccessAuthorizationError("authorization principal email is invalid")
    if "@" not in email or any(char.isspace() for char in email):
        raise AccessAuthorizationError("authorization principal email is invalid")
    return email


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    _by_email: Mapping[str, PrincipalGrant]

    @property
    def principal_count(self) -> int:
        return len(self._by_email)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> AuthorizationPolicy:
        if not isinstance(payload, Mapping):
            raise AccessAuthorizationError("authorization policy must be an object")
        if set(payload) != {"schema_version", "principals"}:
            raise AccessAuthorizationError("authorization policy keys are invalid")
        version = payload.get("schema_version")
        if isinstance(version, bool) or version != 1:
            raise AccessAuthorizationError("authorization policy schema version is invalid")
        principals = payload.get("principals")
        if isinstance(principals, (str, bytes)) or not isinstance(principals, Sequence):
            raise AccessAuthorizationError("authorization policy principals must be a list")
        if not principals:
            raise AccessAuthorizationError("authorization policy requires at least one principal")

        by_email: dict[str, PrincipalGrant] = {}
        for item in principals:
            grant = _parse_grant(item)
            if grant.email in by_email:
                raise AccessAuthorizationError("authorization policy contains duplicate principal")
            by_email[grant.email] = grant
        return cls(MappingProxyType(by_email))

    @classmethod
    def from_file(cls, path: Path) -> AuthorizationPolicy:
        try:
            stat = path.stat()
        except OSError as exc:
            raise AccessAuthorizationError("authorization policy file is unavailable") from exc
        if not path.is_file() or stat.st_size > MAX_POLICY_BYTES:
            raise AccessAuthorizationError("authorization policy file is invalid")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AccessAuthorizationError("authorization policy file is invalid") from exc
        if not isinstance(payload, Mapping):
            raise AccessAuthorizationError("authorization policy must be an object")
        return cls.from_mapping(payload)

    def _grant(self, principal: AuthenticatedPrincipal) -> PrincipalGrant:
        grant = self._by_email.get(principal.email)
        if grant is None:
            raise AccessAuthorizationError("forbidden")
        return grant

    def require_scope(
        self,
        principal: AuthenticatedPrincipal,
        scope_id: ReconciliationScopeId,
    ) -> PrincipalGrant:
        grant = self._grant(principal)
        if ControlTowerRole.SCOPE_VIEWER not in grant.roles or scope_id not in grant.scopes:
            raise AccessAuthorizationError("forbidden")
        return grant

    def require_evaluation(self, principal: AuthenticatedPrincipal) -> PrincipalGrant:
        grant = self._grant(principal)
        if ControlTowerRole.EVALUATION_REVIEWER not in grant.roles:
            raise AccessAuthorizationError("forbidden")
        return grant


def _parse_grant(value: object) -> PrincipalGrant:
    if not isinstance(value, Mapping):
        raise AccessAuthorizationError("authorization principal must be an object")
    if set(value) != {"email", "roles", "scopes"}:
        raise AccessAuthorizationError("authorization principal keys are invalid")
    email = _normalized_email(value.get("email"))

    role_values = value.get("roles")
    if isinstance(role_values, (str, bytes)) or not isinstance(role_values, Sequence):
        raise AccessAuthorizationError("authorization roles must be a list")
    if not role_values:
        raise AccessAuthorizationError("authorization principal requires a role")
    roles: set[ControlTowerRole] = set()
    for role_value in role_values:
        try:
            role = ControlTowerRole(role_value)
        except (TypeError, ValueError) as exc:
            raise AccessAuthorizationError("authorization policy contains unknown role") from exc
        if role in roles:
            raise AccessAuthorizationError("authorization policy contains duplicate role")
        roles.add(role)

    scope_values = value.get("scopes")
    if isinstance(scope_values, (str, bytes)) or not isinstance(scope_values, Sequence):
        raise AccessAuthorizationError("authorization scopes must be a list")
    scopes: set[ReconciliationScopeId] = set()
    for scope_value in scope_values:
        try:
            scope = ReconciliationScopeId(scope_value)
        except (TypeError, ValueError) as exc:
            raise AccessAuthorizationError("authorization policy contains invalid scope") from exc
        if scope in scopes:
            raise AccessAuthorizationError("authorization policy contains duplicate scope")
        scopes.add(scope)

    if ControlTowerRole.SCOPE_VIEWER in roles and not scopes:
        raise AccessAuthorizationError("scope viewer requires at least one scope")
    if ControlTowerRole.SCOPE_VIEWER not in roles and scopes:
        raise AccessAuthorizationError("scope grants require the scope viewer role")
    return PrincipalGrant(email=email, roles=frozenset(roles), scopes=frozenset(scopes))


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise AccessAuthenticationError("Cloudflare Access signing-key redirect refused")


JwksFetcher = Callable[[str, float, int], Mapping[str, object]]


def _default_jwks_fetcher(url: str, timeout: float, max_bytes: int) -> Mapping[str, object]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "reflow-access-verifier/1"},
        method="GET",
    )
    opener = urllib.request.build_opener(_RejectRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise AccessAuthenticationError("Cloudflare Access signing keys unavailable")
            raw = response.read(max_bytes + 1)
    except AccessAuthenticationError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise AccessAuthenticationError("Cloudflare Access signing keys unavailable") from exc
    if len(raw) > max_bytes:
        raise AccessAuthenticationError("Cloudflare Access signing-key response is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AccessAuthenticationError("Cloudflare Access signing keys are invalid") from exc
    if not isinstance(payload, Mapping):
        raise AccessAuthenticationError("Cloudflare Access signing keys are invalid")
    return payload


def _normalize_access_issuer(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AccessAuthenticationError("Cloudflare Access issuer is invalid")
    parsed = urlsplit(value)
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise AccessAuthenticationError("Cloudflare Access issuer is invalid") from exc
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not hostname.endswith(".cloudflareaccess.com")
        or hostname == "cloudflareaccess.com"
    ):
        raise AccessAuthenticationError("Cloudflare Access issuer is invalid")
    return f"https://{hostname.lower()}"


def _positive_bound(value: object, *, name: str, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or value > maximum
    ):
        raise AccessAuthenticationError(f"Cloudflare Access {name} is invalid")
    return float(value)


class CloudflareAccessVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        timeout_seconds: float = DEFAULT_JWKS_TIMEOUT_SECONDS,
        max_jwks_bytes: int = MAX_JWKS_RESPONSE_BYTES,
        cache_seconds: float = DEFAULT_JWKS_CACHE_SECONDS,
        jwks_fetcher: JwksFetcher = _default_jwks_fetcher,
    ) -> None:
        self.issuer = _normalize_access_issuer(issuer)
        if not isinstance(audience, str) or not audience or audience != audience.strip():
            raise AccessAuthenticationError("Cloudflare Access audience is invalid")
        if len(audience) > 512 or any(char.isspace() for char in audience):
            raise AccessAuthenticationError("Cloudflare Access audience is invalid")
        self.audience = audience
        self.timeout_seconds = _positive_bound(
            timeout_seconds,
            name="timeout",
            maximum=MAX_JWKS_TIMEOUT_SECONDS,
        )
        if (
            isinstance(max_jwks_bytes, bool)
            or not isinstance(max_jwks_bytes, int)
            or not 1 <= max_jwks_bytes <= MAX_JWKS_RESPONSE_BYTES
        ):
            raise AccessAuthenticationError("Cloudflare Access JWKS byte limit is invalid")
        self.max_jwks_bytes = max_jwks_bytes
        self.cache_seconds = _positive_bound(
            cache_seconds,
            name="JWKS cache lifetime",
            maximum=3600.0,
        )
        if not callable(jwks_fetcher):
            raise AccessAuthenticationError("Cloudflare Access JWKS fetcher is invalid")
        self._jwks_fetcher = jwks_fetcher
        self._jwks_url = f"{self.issuer}/cdn-cgi/access/certs"
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None

    def _cache_expired(self) -> bool:
        if self._fetched_at is None:
            return True
        return time.monotonic() - self._fetched_at >= self.cache_seconds

    def _refresh_keys(self) -> None:
        payload = self._jwks_fetcher(
            self._jwks_url,
            self.timeout_seconds,
            self.max_jwks_bytes,
        )
        values = payload.get("keys")
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
            raise AccessAuthenticationError("Cloudflare Access signing keys are invalid")
        parsed: dict[str, jwt.PyJWK] = {}
        for value in values:
            if not isinstance(value, Mapping):
                continue
            kid = value.get("kid")
            alg = value.get("alg")
            key_type = value.get("kty")
            key_use = value.get("use")
            if (
                not isinstance(kid, str)
                or not kid
                or alg not in {None, "RS256"}
                or key_type != "RSA"
                or key_use not in {None, "sig"}
            ):
                continue
            if kid in parsed:
                raise AccessAuthenticationError("Cloudflare Access signing keys are invalid")
            try:
                parsed[kid] = jwt.PyJWK.from_dict(dict(value), algorithm="RS256")
            except (jwt.PyJWTError, TypeError, ValueError):
                continue
        if not parsed:
            raise AccessAuthenticationError("Cloudflare Access signing keys are invalid")
        self._keys = parsed
        self._fetched_at = time.monotonic()

    def _key(self, kid: str) -> jwt.PyJWK:
        if self._cache_expired():
            self._refresh_keys()
        key = self._keys.get(kid)
        if key is not None:
            return key
        self._refresh_keys()
        key = self._keys.get(kid)
        if key is None:
            raise AccessAuthenticationError("Cloudflare Access signing key is unavailable")
        return key

    def verify(self, token: str) -> AuthenticatedPrincipal:
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("utf-8")) > MAX_ACCESS_TOKEN_BYTES
            or token.count(".") != 2
        ):
            raise AccessAuthenticationError("authentication required")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AccessAuthenticationError("authentication required") from exc
        if header.get("alg") != "RS256" or header.get("typ") not in {None, "JWT"}:
            raise AccessAuthenticationError("authentication required")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise AccessAuthenticationError("authentication required")
        key = self._key(kid)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=30,
                options={
                    "require": ["iss", "aud", "exp", "iat", "nbf", "type", "sub", "email"]
                },
            )
        except jwt.PyJWTError as exc:
            raise AccessAuthenticationError("authentication required") from exc
        if claims.get("type") != "app":
            raise AccessAuthenticationError("authentication required")
        subject = claims.get("sub")
        if (
            not isinstance(subject, str)
            or not subject
            or subject != subject.strip()
            or len(subject) > 512
        ):
            raise AccessAuthenticationError("authentication required")
        try:
            email = _normalized_email(claims.get("email"))
        except AccessAuthorizationError as exc:
            raise AccessAuthenticationError("authentication required") from exc
        return AuthenticatedPrincipal(subject=subject, email=email)


@dataclass(frozen=True, slots=True)
class AccessAuthBoundary:
    verifier: CloudflareAccessVerifier
    policy: AuthorizationPolicy

    def authenticate(self, assertion: str | None) -> AuthenticatedPrincipal:
        if assertion is None:
            raise AccessAuthenticationError("authentication required")
        return self.verifier.verify(assertion)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required when REFLOW_AUTH_MODE=cloudflare_access")
    if value != value.strip():
        raise RuntimeError(f"{name} cannot contain surrounding whitespace")
    return value


def auth_boundary_from_env() -> AccessAuthBoundary | None:
    raw_mode = os.getenv("REFLOW_AUTH_MODE")
    if raw_mode is None or not raw_mode.strip():
        raise RuntimeError("REFLOW_AUTH_MODE is required for environment-based serving")
    if raw_mode != raw_mode.strip():
        raise RuntimeError("REFLOW_AUTH_MODE cannot contain surrounding whitespace")
    mode = raw_mode.lower()
    if mode == "disabled":
        return None
    if mode != "cloudflare_access":
        raise RuntimeError("REFLOW_AUTH_MODE must be 'disabled' or 'cloudflare_access'")
    issuer = _required_env("REFLOW_CF_ACCESS_ISSUER")
    audience = _required_env("REFLOW_CF_ACCESS_AUD")
    policy_path = Path(_required_env("REFLOW_AUTHZ_POLICY"))
    try:
        verifier = CloudflareAccessVerifier(issuer=issuer, audience=audience)
        policy = AuthorizationPolicy.from_file(policy_path)
    except (AccessAuthenticationError, AccessAuthorizationError) as exc:
        raise RuntimeError("Cloudflare Access authentication configuration is invalid") from exc
    return AccessAuthBoundary(verifier=verifier, policy=policy)
