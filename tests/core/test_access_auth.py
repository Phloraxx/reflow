from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from reflow.access_auth import (
    AccessAuthenticationError,
    AccessAuthorizationError,
    AuthenticatedPrincipal,
    AuthorizationPolicy,
    CloudflareAccessVerifier,
    ControlTowerRole,
    _default_jwks_fetcher,
    _RejectRedirectHandler,
    auth_boundary_from_env,
)
from reflow.domain import ReconciliationScopeId

ISSUER = "https://reflow-test.cloudflareaccess.com"
AUDIENCE = "audience-for-reflow"
SCOPE_A = ReconciliationScopeId("scope_auth_a")
SCOPE_B = ReconciliationScopeId("scope_auth_b")

def _key_material(kid: str = "kid-1"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_key, jwk


def _token(
    private_key,
    *,
    kid: str = "kid-1",
    issuer: str = ISSUER,
    audience: object = AUDIENCE,
    email: str = "viewer@example.com",
    subject: str = "subject-1",
    token_type: str = "app",
    algorithm: str = "RS256",
    exp_offset: int = 300,
    nbf_offset: int = -1,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "email": email,
            "sub": subject,
            "type": token_type,
            "iat": now - 1,
            "nbf": now + nbf_offset,
            "exp": now + exp_offset,
        },
        private_key,
        algorithm=algorithm,
        headers={"kid": kid, "typ": "JWT"},
    )

def _policy() -> AuthorizationPolicy:
    return AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "viewer@example.com",
                    "roles": ["scope_viewer"],
                    "scopes": [str(SCOPE_A)],
                },
                {
                    "email": "reviewer@example.com",
                    "roles": ["scope_viewer", "evaluation_reviewer"],
                    "scopes": [str(SCOPE_A), str(SCOPE_B)],
                },
            ],
        }
    )


def _verifier(private_key=None, jwk=None, *, fetcher=None) -> CloudflareAccessVerifier:
    if private_key is None or jwk is None:
        private_key, jwk = _key_material()
    if fetcher is None:
        def default_fetcher(_url: str, _timeout: float, _max_bytes: int):
            return {"keys": [jwk]}

        fetcher = default_fetcher
    return CloudflareAccessVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_fetcher=fetcher,
    )

def test_verified_access_identity_and_exact_scope_authorization() -> None:
    private_key, jwk = _key_material()
    principal = _verifier(private_key, jwk).verify(_token(private_key))
    assert principal.subject == "subject-1"
    assert principal.email == "viewer@example.com"

    policy = _policy()
    granted = policy.require_scope(principal, SCOPE_A)
    assert granted.email == "viewer@example.com"
    assert ControlTowerRole.SCOPE_VIEWER in granted.roles

    with pytest.raises(AccessAuthorizationError):
        policy.require_scope(principal, SCOPE_B)
    with pytest.raises(AccessAuthorizationError):
        policy.require_evaluation(principal)


def test_evaluation_role_is_separate_from_scope_access() -> None:
    private_key, jwk = _key_material()
    principal = _verifier(private_key, jwk).verify(
        _token(private_key, email="reviewer@example.com", subject="subject-reviewer")
    )
    policy = _policy()
    policy.require_scope(principal, SCOPE_B)
    policy.require_evaluation(principal)

def test_access_verifier_rejects_wrong_issuer_audience_and_token_type() -> None:
    private_key, jwk = _key_material()
    verifier = _verifier(private_key, jwk)

    for token in (
        _token(private_key, issuer="https://wrong.cloudflareaccess.com"),
        _token(private_key, audience="other-audience"),
        _token(private_key, token_type="org"),
        _token(private_key, subject=""),
        _token(private_key, email=""),
    ):
        with pytest.raises(AccessAuthenticationError):
            verifier.verify(token)


def test_access_verifier_rejects_non_access_issuer_and_invalid_bounds() -> None:
    with pytest.raises(AccessAuthenticationError, match="issuer"):
        CloudflareAccessVerifier(issuer="http://example.com", audience=AUDIENCE)
    with pytest.raises(AccessAuthenticationError, match="issuer"):
        CloudflareAccessVerifier(issuer="https://example.com", audience=AUDIENCE)
    with pytest.raises(AccessAuthenticationError, match="audience"):
        CloudflareAccessVerifier(issuer=ISSUER, audience="")
    with pytest.raises(AccessAuthenticationError, match="timeout"):
        CloudflareAccessVerifier(issuer=ISSUER, audience=AUDIENCE, timeout_seconds=True)

def test_unknown_signing_key_refreshes_jwks_once() -> None:
    old_private, old_jwk = _key_material("old-kid")
    new_private, new_jwk = _key_material("new-kid")
    calls = 0

    def fetcher(_url: str, _timeout: float, _max_bytes: int) -> Mapping[str, object]:
        nonlocal calls
        calls += 1
        return {"keys": [old_jwk] if calls == 1 else [new_jwk]}

    verifier = _verifier(old_private, old_jwk, fetcher=fetcher)
    assert verifier.verify(_token(old_private, kid="old-kid")).email == "viewer@example.com"
    assert verifier.verify(_token(new_private, kid="new-kid")).subject == "subject-1"
    assert calls == 2


def test_policy_parser_rejects_duplicate_principal_unknown_role_and_bad_scope() -> None:
    duplicate = {
        "schema_version": 1,
        "principals": [
            {"email": "a@example.com", "roles": ["scope_viewer"], "scopes": ["scope_a"]},
            {"email": "A@example.com", "roles": ["scope_viewer"], "scopes": ["scope_b"]},
        ],
    }
    with pytest.raises(AccessAuthorizationError, match="duplicate"):
        AuthorizationPolicy.from_mapping(duplicate)

    with pytest.raises(AccessAuthorizationError, match="role"):
        AuthorizationPolicy.from_mapping(
            {
                "schema_version": 1,
                "principals": [
                    {"email": "a@example.com", "roles": ["owner"], "scopes": ["scope_a"]}
                ],
            }
        )
    with pytest.raises(AccessAuthorizationError, match="scope"):
        AuthorizationPolicy.from_mapping(
            {
                "schema_version": 1,
                "principals": [
                    {
                        "email": "a@example.com",
                        "roles": ["scope_viewer"],
                        "scopes": ["bad"],
                    }
                ],
            }
        )

def test_auth_boundary_env_disabled_and_cloudflare_modes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("REFLOW_AUTH_MODE", raising=False)
    with pytest.raises(RuntimeError, match="REFLOW_AUTH_MODE is required"):
        auth_boundary_from_env()
    monkeypatch.setenv("REFLOW_AUTH_MODE", "disabled")
    assert auth_boundary_from_env() is None

    policy_path = tmp_path / "authz.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "principals": [
                    {
                        "email": "viewer@example.com",
                        "roles": ["scope_viewer"],
                        "scopes": [str(SCOPE_A)],
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("REFLOW_AUTH_MODE", "cloudflare_access")
    monkeypatch.setenv("REFLOW_CF_ACCESS_ISSUER", ISSUER)
    monkeypatch.setenv("REFLOW_CF_ACCESS_AUD", AUDIENCE)
    monkeypatch.setenv("REFLOW_AUTHZ_POLICY", str(policy_path))
    boundary = auth_boundary_from_env()
    assert boundary is not None
    assert boundary.policy.principal_count == 1


def test_cloudflare_auth_startup_fails_closed_without_required_configuration(monkeypatch) -> None:
    monkeypatch.setenv("REFLOW_AUTH_MODE", "cloudflare_access")
    monkeypatch.delenv("REFLOW_CF_ACCESS_ISSUER", raising=False)
    monkeypatch.delenv("REFLOW_CF_ACCESS_AUD", raising=False)
    monkeypatch.delenv("REFLOW_AUTHZ_POLICY", raising=False)
    with pytest.raises(RuntimeError, match="REFLOW_CF_ACCESS_ISSUER"):
        auth_boundary_from_env()

    monkeypatch.setenv("REFLOW_AUTH_MODE", "unexpected")
    with pytest.raises(RuntimeError, match="REFLOW_AUTH_MODE"):
        auth_boundary_from_env()


def test_access_verifier_rejects_expired_future_and_wrong_algorithm_tokens() -> None:
    private_key, jwk = _key_material()
    verifier = _verifier(private_key, jwk)
    with pytest.raises(AccessAuthenticationError):
        verifier.verify(_token(private_key, exp_offset=-120))
    with pytest.raises(AccessAuthenticationError):
        verifier.verify(_token(private_key, nbf_offset=120))

    now = int(time.time())
    wrong_algorithm = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "email": "viewer@example.com",
            "sub": "subject-1",
            "type": "app",
            "iat": now - 1,
            "nbf": now - 1,
            "exp": now + 300,
        },
        "test-only-hmac-key-that-is-long-enough-1234",
        algorithm="HS256",
        headers={"kid": "kid-1", "typ": "JWT"},
    )
    with pytest.raises(AccessAuthenticationError):
        verifier.verify(wrong_algorithm)


def test_jwks_transport_refuses_redirect_and_oversized_response(monkeypatch) -> None:
    with pytest.raises(AccessAuthenticationError, match="redirect"):
        _RejectRedirectHandler().redirect_request(None, None, 302, "Moved", {}, "https://other")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self, amount: int) -> bytes:
            return b"x" * amount

    class Opener:
        def open(self, _request, timeout: float):
            assert timeout == 1.0
            return Response()

    monkeypatch.setattr(
        "reflow.access_auth.urllib.request.build_opener",
        lambda *_handlers: Opener(),
    )
    with pytest.raises(AccessAuthenticationError, match="too large"):
        _default_jwks_fetcher(
            f"{ISSUER}/cdn-cgi/access/certs",
            1.0,
            32,
        )


def test_checked_in_authorization_policy_example_is_valid() -> None:
    policy = AuthorizationPolicy.from_file(Path("config/authz.example.json"))
    assert policy.principal_count == 3


def test_case_operator_role_is_scope_bound_and_separate_from_viewer() -> None:
    principal = AuthenticatedPrincipal(subject="subject-operator", email="operator@example.com")
    policy = AuthorizationPolicy.from_mapping(
        {
            "schema_version": 1,
            "principals": [
                {
                    "email": "operator@example.com",
                    "roles": ["case_operator"],
                    "scopes": [str(SCOPE_A)],
                }
            ],
        }
    )
    grant = policy.require_case_operator(principal, SCOPE_A)
    assert ControlTowerRole.CASE_OPERATOR in grant.roles
    with pytest.raises(AccessAuthorizationError):
        policy.require_case_operator(principal, SCOPE_B)
    with pytest.raises(AccessAuthorizationError):
        policy.require_scope(principal, SCOPE_A)


def test_scoped_roles_require_scope_and_non_scoped_roles_cannot_receive_scope() -> None:
    with pytest.raises(AccessAuthorizationError, match="requires at least one scope"):
        AuthorizationPolicy.from_mapping(
            {
                "schema_version": 1,
                "principals": [
                    {"email": "operator@example.com", "roles": ["case_operator"], "scopes": []}
                ],
            }
        )
    with pytest.raises(AccessAuthorizationError, match="require a scoped role"):
        AuthorizationPolicy.from_mapping(
            {
                "schema_version": 1,
                "principals": [
                    {
                        "email": "reviewer@example.com",
                        "roles": ["evaluation_reviewer"],
                        "scopes": [str(SCOPE_A)],
                    }
                ],
            }
        )
