# Razorpay Webhook Ingress Contract

**Started:** 2026-09-03
**Base `main`:** `ab5467922c66f979242033a1680607b6fdd793cd`
**Branch:** `hardening/razorpay-webhook-ingress-ci`

## Goal

Add a production-safe Razorpay webhook HTTP boundary without giving provider delivery or AI any authority to decide financial truth.

The boundary separates three facts:

1. Razorpay authenticated this exact HTTP body with a configured webhook secret;
2. ReFlow durably retained the exact delivery and can replay internal processing;
3. downstream deterministic compilation either accepted or rejected the retained evidence.

Only the deterministic reconciliation pipeline can later decide whether money reconciles.

## Service isolation

Webhook ingress runs as a dedicated public ASGI service rather than sharing the human Control Tower application. Its HTTP surface contains only health, readiness, and the Razorpay webhook endpoint.

The existing Control Tower remains behind Cloudflare Access unchanged. This gate deliberately does not add an internet-facing operator API or weaken its authentication boundary just to receive provider callbacks.

## Provider-facing receipt semantics

The public endpoint reads the raw ASGI body with a fixed byte cap before JSON parsing. It requires `X-Razorpay-Signature` and `x-razorpay-event-id`, verifies HMAC-SHA256 over the exact raw bytes, and never accepts caller-supplied account configuration.

A delivery receives 2xx only after an authenticated receipt is durably present in PostgreSQL. Exact redelivery of the same event/body is idempotent. The same event id with a different body is a conflict and is not acknowledged as a successful receipt.

Signed-but-unprocessable deliveries are retained first, then receive a durable processing outcome and a 2xx acknowledgement. They do not rely on repeated provider delivery to become operator-visible.

If signature verification fails, the body is too large, required transport identity is missing, or PostgreSQL cannot durably retain an authenticated receipt, the endpoint fails closed without claiming acceptance.

## Persistence boundary

Webhook transport state is not a financial `SourceKind`. It therefore uses a separate PostgreSQL subsystem with its own schema metadata and tables:

- immutable receipt identity: provider + configured account + event id;
- exact raw-body SHA-256 and exact raw bytes;
- original provider HMAC signature and verified-secret generation;
- first receipt time;
- append-only processing attempts with bounded public outcome code;
- no webhook secret, Authorization header or API key persisted.

The signature is retained only so replay can traverse the same Gate 15 verification/compilation evidence path. Operator output never returns the raw body or signature.

The subsystem is independently schema-versioned so transport evolution does not silently change the financial application schema contract.

## Processing and replay

After durable receipt, ReFlow parses the retained bytes and dispatches only supported payment/settlement webhook families through the existing Gate 15 compiler. Internal replay always reads the retained body; callers cannot supply replacement payloads.

Every attempt records a terminal `processed` or `rejected` outcome. Rejection codes are bounded and non-secret. Replaying a rejected receipt creates a new attempt; it never rewrites the original receipt or earlier outcome.

Replay re-verifies the retained body/signature against the currently configured current/previous webhook secrets before invoking Gate 15. If the receipt is older than the configured rotation window, replay fails closed with a bounded `verification_key_unavailable` outcome instead of fabricating a signature.

## Secret rotation

The runtime may configure a current and one previous Razorpay webhook secret. Verification tries both without exposing which value matched outside the process; persistence records only generation `current` or `previous`.

The previous secret exists only to cover provider retry windows during controlled rotation and should be removed after that window closes.

## Operator boundary

This gate exposes inspection and replay only through the privileged local CLI `python -m reflow.webhook_cli`. The CLI returns receipt metadata and processing outcomes, never raw webhook bytes, signatures, webhook secrets or provider credentials.

A future human UI/control API may expose the same operations behind Cloudflare Access as a separate authorization change. That is intentionally not bundled into the public ingress service.

Replay is an operator action, not a finance mutation: it can create another processing attempt and canonical evidence from the immutable receipt, but cannot create a proof, mark a case green, or update reconciliation disposition directly.

## Recovery boundary

The independently versioned webhook tables are included naturally in PostgreSQL logical dumps. The CI recovery drill restores a database containing a webhook receipt and processing attempt, then independently reopens the webhook subsystem with initialization disabled and verifies its schema and integrity inventory.

The generic financial recovery verifier remains responsible only for financial application tables; this gate does not silently widen that existing contract.

## Acceptance criteria

1. body-size enforcement occurs while streaming, before JSON parsing;
2. signature verification uses exact raw bytes and constant-time comparison;
3. authenticated receipt is durable before any provider 2xx;
4. exact redelivery is idempotent; conflicting redelivery fails closed;
5. malformed/unsupported signed events remain operator-visible after 2xx;
6. PostgreSQL failure before receipt persistence returns non-2xx;
7. current/previous secret rotation is regression-covered;
8. the public webhook service is isolated from the Access-protected Control Tower;
9. raw body/signature/secrets are never returned by public responses or operator CLI output;
10. a real PostgreSQL 16 logical backup/restore drill preserves and revalidates webhook tables;
11. full PostgreSQL reviewer suite and frozen evaluation evidence remain green.

## Validation checkpoint

Exact implementation/environment-contract head `5db4ecc1f7fbec2789cab6051534861ee8a5ed67` passed PR #33 CI run `33779934431`.

The required submission check reported:

- Ruff: passed;
- strict mypy: passed across 72 source modules;
- Python/PostgreSQL: **520 tests passed with no skips**;
- TypeScript project check: passed;
- React/Vitest: **5/5 tests passed**;
- Vite production build: passed;
- frozen Gate 17/Gate 19 artifacts and generated `EVALUATION.md`: verified unchanged.

Because the CI-only webhook recovery test is gated on the PostgreSQL DSN plus `REFLOW_RECOVERY_DOCKER_DRILL=1`, the no-skip 520-test result confirms that the digest-pinned PostgreSQL 16.15 dump -> fresh database -> restore -> webhook schema/integrity verification drill executed successfully on that head.

PR #33 final head `a41e8f976e5be64ae2b4d5dab963c18d6351107c` passed exact PR CI run `33780396829`, including the same 520-test PostgreSQL-enabled submission check and frozen-artifact verification.

PR #33 was merged with head-SHA protection as `41f62d9fd07a8f232f3e77476e516d4b666e6d96`. Exact merge-triggered `main` CI run `33781209886` then passed the full required submission check.

**Gate status: closed and merged green.**

## Non-claims

This gate does not claim a distributed queue, cross-region webhook ingestion, provider IP allowlisting, unlimited throughput, authenticated webhook-operator UI, or live settlement accuracy. Production Cloudflare/reverse-proxy configuration must route Razorpay only to the dedicated webhook service while preserving Access protection for human Control Tower routes.
