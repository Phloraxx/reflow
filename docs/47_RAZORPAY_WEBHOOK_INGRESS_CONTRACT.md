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

The signature is retained only so replay can traverse the same Gate 15 verification/compilation evidence path; operator APIs never return it.

The subsystem is independently schema-versioned so transport evolution does not silently change the financial application schema contract.

## Processing and replay

After durable receipt, ReFlow parses the retained bytes and dispatches only supported payment/settlement webhook families through the existing Gate 15 compiler. Internal replay always reads the retained body; callers cannot supply replacement payloads.

Every attempt records a terminal `processed` or `rejected` outcome. Rejection codes are bounded and non-secret. Replaying a rejected receipt creates a new attempt; it never rewrites the original receipt or earlier outcome.

## Secret rotation

The runtime may configure a current and one previous Razorpay webhook secret. Verification tries both without exposing which value matched outside the process; persistence records only generation `current` or `previous`.

The previous secret exists only to cover provider retry windows during controlled rotation and should be removed after that window closes.

## Operator boundary

Human read/replay endpoints remain behind the existing Cloudflare Access identity boundary. A dedicated `webhook_operator` role is separate from `scope_viewer` and `evaluation_reviewer`.

Receipt listing/detail exposes metadata and processing outcomes, never raw webhook bytes, signatures, webhook secrets or provider credentials.

Replay is an operator action, not a finance mutation: it can create another processing attempt and canonical evidence from the immutable receipt, but cannot create a proof, mark a case green, or update reconciliation disposition directly.

## Acceptance criteria

1. body-size enforcement occurs while streaming, before JSON parsing;
2. signature verification uses exact raw bytes and constant-time comparison;
3. authenticated receipt is durable before any provider 2xx;
4. exact redelivery is idempotent; conflicting redelivery fails closed;
5. malformed/unsupported signed events remain operator-visible after 2xx;
6. PostgreSQL failure before receipt persistence returns non-2xx;
7. current/previous secret rotation is regression-covered;
8. operator receipt/replay routes require existing authenticated authorization;
9. raw body/signature/secrets are never returned by operator APIs or ordinary logs;
10. backup/restore integrity includes the independently versioned webhook tables;
11. full PostgreSQL reviewer suite and frozen evaluation evidence remain green.

## Non-claims

This gate does not claim a distributed queue, cross-region webhook ingestion, provider IP allowlisting, unlimited throughput, or live settlement accuracy. Production Cloudflare configuration must allow Razorpay to reach only the webhook path while preserving Access protection for human routes.
