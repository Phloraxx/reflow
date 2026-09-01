# Gate 15 Checkpoint — Real Razorpay Integration

## Status

Gate 15 is implemented on `build/gate-15-real-razorpay-integration` from the final Gate 14 `main` checkpoint:

`fec0693afbc8b8f0e9bb7bb1769e15101ba06d2b`

Code/test checkpoint:

`190dd2a08f39b85f1da870d3a5a896ea6d49dd47`

Merged checkpoint:

- PR #15: `https://github.com/Phloraxx/reflow/pull/15`;
- merge commit: `5396f5d884012f05975a751e35fc3fdf5cd40cc8`;
- merge-triggered `main` CI run: `33522206484` — passed.

Oracle VM validation on 2026-09-01:

- Ruff: passed;
- strict mypy: passed across 52 source files;
- targeted Gate 15 suite: 41 collected cases;
- full repository suite: 310 collected cases and all passed;
- `git diff --check`: passed;
- provider-module scan: no simulator import, TODO, FIXME or `NotImplemented` marker.

Gate 15 adds no investigation-agent code and gives no provider/API payload authority to mark money reconciled. Provider evidence enters the existing deterministic proof kernel.

## Gate 15 thesis

> Preserve raw Razorpay evidence first, then deterministically normalize actual provider semantics into the existing audited ReFlow domain without importing synthetic fixture assumptions.

Gate 15 is a provider boundary, not a second reconciliation engine.

## Provider semantics re-verified

The implementation was checked against the current official Razorpay documentation during Gate 15:

- Settlement Recon: `https://razorpay.com/docs/api/settlements/fetch-recon/`
- standard Settlement entity: `https://razorpay.com/docs/api/settlements/entity/`
- Settlement webhook events: `https://razorpay.com/docs/webhooks/settlements/`
- Instant Settlement fetch semantics: `https://razorpay.com/docs/api/settlements/instant/fetch-with-id/`

The provider contract used by Gate 15 is therefore explicit:

- recon direction comes from `credit - debit`;
- recon types are payment/refund/transfer/adjustment;
- standard settlement identity is `setl_...`;
- `settlement.processed` does not prove bank credit;
- UTR remains the bank-reconciliation identity;
- standard settlement entity/webhook shapes do not expose a settlement `currency` field;
- Instant Settlement `setlod_...` is a separate product shape and is not coerced into the standard settlement model.

## Explicit evidence origin

`RazorpayAccountContext` carries:

- expected merchant/account ID;
- evidence origin;
- standard-settlement account currency (currently INR).

Allowed provider origins are:

- `PROVIDER_DOC_FIXTURE`;
- `REAL_TEST_MODE`;
- `REAL_LIVE`.

`SYNTHETIC` is rejected by the Gate 15 provider API. Origin is explicit caller/application context; provider-looking JSON is never automatically promoted to real evidence.

## Signed payment webhook boundary

Supported payment transitions are:

- `payment.authorized`;
- `payment.captured`;
- `payment.failed`.

The compiler:

1. verifies HMAC-SHA256 over the exact raw request bytes;
2. requires `x-razorpay-event-id`;
3. validates account scope;
4. journals the signed raw body and relevant auth headers;
5. validates the retained top-level event envelope;
6. derives the canonical transition from the signed event name, not mutable entity snapshot status.

Exact duplicate event delivery is idempotent. Reuse of one event ID with different signed content is retained as conflicting evidence and fails closed. Delivery ordering is not assumed.

Malformed event timestamps no longer bypass the journal: optional journal time metadata fails soft, then canonical timestamp validation fails from retained evidence.

## Settlement Recon provider normalization

Provider recon items are journaled before semantic normalization.

Gate 15 uses:

```text
settlement_effect = credit - debit
```

It does not reuse the synthetic fixture rule `gross - fee - tax`.

Examples frozen by tests include the official provider shapes:

- payment: gross `100000`, fee `2900`, credit/effect `97100`;
- refund: debit/effect `242500` negative;
- transfer: amount `100000`, fee `296`, tax `46`, provider debit/effect `100296` negative;
- adjustment: direct credit/effect `1012`.

This avoids double-counting tax when provider `fee` already represents the charged fee total described by the provider response.

### Two-phase raw retention

A recon response is processed in two phases:

1. retain every safely identifiable raw provider row, continuing through retainable identity conflicts;
2. normalize only the retained immutable envelopes.

Therefore one malformed early row cannot make later rows from the same supplied provider response disappear from the raw journal.

### Stable provider/canonical identity

Raw recon identity contains account, settlement ID, type and entity ID. Canonical `ReconEntryId` is deterministic from that provider economic identity. `SourceLink` binds the raw provider identity/envelope to the canonical ID.

## Provider UTR identity reaches Gate 7

Gate 15 exposed a pre-existing canonical gap: `SettlementReconEntry` did not retain provider `settlement_utr`.

The fix intentionally changes proof semantics:

- canonical compilation contract: `canonical-source-link-v3`;
- Gate 7 composition ruleset: `gate7-composition-v2`;
- canonical recon entries retain optional `settlement_utr`;
- a non-null recon UTR that contradicts a non-null settlement UTR produces `SETTLEMENT_UTR_MISMATCH` and `COMPOSITION_CONTRADICTED`;
- the mismatched component is excluded from proof arithmetic.

Exact amount arithmetic can therefore no longer mask contradictory provider payout identity.

## Standard settlement webhook

`settlement.processed` is normalized only when:

- outer signed envelope is a Razorpay event containing `settlement`;
- embedded entity is `settlement`;
- status is `processed`;
- ID is a standard `setl_...` ID;
- amount/UTR/provider timestamps satisfy the deterministic contract.

The documented settlement payload has no `currency` field. Gate 15 obtains the standard-settlement currency from explicit account context and rejects a conflicting supplied currency.

Canonical `processed_at` for a webhook uses the signed top-level webhook event timestamp.

## Processed settlement API entity

`compile_settlement_api_entity()` provides the journal-first reference path for an authenticated connector/API read.

For a processed API entity:

- the raw entity is retained first;
- provider `created_at` is retained and validated as entity timing;
- canonical `processed_at` is the ReFlow `received_at` observation time, because that is the point at which this API read actually proves the entity was already processed;
- `created_at` is not misrepresented as processing time or bank-credit time.

Unprocessed or malformed identity-recoverable API entities remain raw evidence and are rejected from canonical settlement composition.

## Bank-credit separation remains intact

A processed standard settlement with no bank evidence produces Gate 8 `WAITING`, not `PROVEN`.

Gate 15 does not infer bank receipt from:

- settlement status;
- settlement webhook delivery;
- UTR presence alone;
- provider API observation.

Bank receipt remains an independent evidence proof.

## Existing proof-kernel compatibility

A Gate 15 provider-shaped fixture combining:

- provider recon evidence;
- signed standard settlement evidence;
- independently journaled bank credit evidence;

passes through the unchanged Money Graph, Gate 7, Gate 8 and Gate 9 ledger and reaches `PROVEN_RECONCILED` only when all exact identities/arithmetic are consistent.

The full proof cites three independent raw source envelopes. Gate 15 adds no provider-specific matching or reconciliation shortcut.

## Connected-account evidence non-claim

The connected read-only Razorpay account was inspected during Gate 15. It exposed payment records, but no settlement records and no settlement-recon rows for the inspected data set.

No private account payload is checked into the repository.

Therefore Gate 15 does **not** claim a real Test Mode settlement/reconciliation accuracy result. Settlement/recon regression fixtures are explicitly labelled `PROVIDER_DOC_FIXTURE` until authenticated Test Mode settlement data actually exists.

## Genuine failures discovered

Permanent details are in `FAILURE_LOG.md`.

- F-0071 — provider recon UTR identity was discarded before Gate 7 proof;
- F-0072 — settlement compiler required a provider `currency` field Razorpay does not expose;
- F-0073 — malformed provider timestamps could fail before raw retention;
- F-0074 — an early recon semantic failure could prevent later raw response rows from being journaled;
- F-0075 — signed webhook schema drift could bypass the outer event-envelope contract.

All five have checked-in regressions and are resolved at the code checkpoint above.

## Acceptance evidence

The hardened Gate 15 suite contains 41 collected cases covering:

- raw-byte webhook signature verification;
- event identity/replay/conflict behavior;
- account and outer-envelope validation;
- out-of-order payment transitions;
- raw-before-normalization timestamp failure behavior;
- provider payment/refund/transfer/adjustment recon arithmetic;
- debit/credit direction and entity-prefix rejection;
- two-phase recon raw retention;
- stable raw→canonical recon identity;
- standard settlement webhook shape without invented currency;
- processed settlement API observation semantics;
- standard-vs-Instant Settlement separation;
- explicit evidence origin labels;
- provider UTR contradiction handling;
- independent Gate 8 bank-wait behavior;
- source-order-invariant payment webhook compilation;
- Gate 9 full-proof compatibility;
- simulator import exclusion and journal-first public API boundaries.

## Non-goals and remaining limitations

Gate 15 does **not** claim:

- a real Test Mode settlement/recon corpus where none exists in the connected account;
- live settlement/recon accuracy;
- an HTTP webhook server;
- durable credentials or webhook-secret storage;
- authenticated application-user identity;
- scheduled recon polling;
- OAuth/merchant onboarding;
- a production bank connector;
- Instant Settlement `setlod`/`setlodp` proof topology;
- non-INR canonical settlement support;
- durable provider-event persistence beyond the current reference journal;
- AI investigation;
- final scale/held-out benchmark results.

`REAL_TEST_MODE` and `REAL_LIVE` remain explicit application trust labels. The reference library does not independently authenticate the caller that constructs `RazorpayAccountContext`.

## Next gate

New Gate 16 is the **Bounded Exception Investigation Agent**.

It may only operate on deterministic proof/case packets with read-only evidence tools. It cannot mark money reconciled, approve adapters, mutate ledgers, attach arbitrary evidence, issue refunds/payouts or execute arbitrary SQL.

Gate 15 PR CI and merge-triggered `main` CI are green. Gate 16 may now begin from the verified merge checkpoint above.
