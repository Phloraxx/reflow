# Gate 15 Contract and Acceptance Plan — Real Razorpay Integration

## Status

Planning/acceptance contract for New Gate 15, started from verified Gate 14 `main` at:

`fec0693afbc8b8f0e9bb7bb1769e15101ba06d2b`

Gate 14 is merged and green. No exception-investigation agent code is admitted into this gate.

## Gate 15 thesis

> Preserve raw Razorpay evidence first, then deterministically normalize provider semantics into the existing audited ReFlow domain without importing synthetic fixture assumptions.

Gate 15 is a provider boundary, not a second reconciliation engine.

## Evidence origin

Every Gate 15 provider input carries an explicit origin label:

- `PROVIDER_DOC_FIXTURE` — payload derived from current official Razorpay documentation examples;
- `REAL_TEST_MODE` — payload retrieved from an authenticated Razorpay Test Mode context;
- `REAL_LIVE` — payload retrieved from an authenticated live merchant context.

`SYNTHETIC` is not accepted by the provider compiler. Synthetic/normalized fixtures remain owned by the existing ingestion path.

No payload is promoted to `REAL_TEST_MODE` or `REAL_LIVE` because it merely looks provider-shaped.

At this checkpoint, no real settlement/recon corpus is claimed. Provider-shaped settlement/recon tests use explicitly labelled `PROVIDER_DOC_FIXTURE` evidence.

## Raw evidence before interpretation

Gate 15 must not convert a Razorpay payload into the old normalized row contract and only then journal it.

For every supported provider input:

1. validate only the minimum envelope/authenticity preconditions needed to identify the source safely;
2. append the raw provider-shaped evidence to the immutable journal;
3. normalize the retained raw payload into existing canonical domain objects;
4. bind canonical identity back to the raw envelope with `SourceLink`.

A semantically invalid provider item is still retained as raw evidence before normalization fails, provided the raw source identity can be established safely.

## Razorpay account context

`RazorpayAccountContext` binds:

- expected Razorpay `account_id` / merchant account identity;
- evidence origin;
- standard-settlement account currency (currently INR).

For signed webhooks, the body-level `account_id` must equal the expected context.

For API response items, the account context comes from the authenticated connector/API session that fetched them. The current reference API accepts that context explicitly; this is an application trust boundary, not a cryptographic proof of the caller's identity.

## Webhook authenticity and replay identity

Supported payment webhooks:

- `payment.authorized`;
- `payment.captured`;
- `payment.failed`.

Supported settlement webhook:

- `settlement.processed`.

Webhook rules:

- verify `X-Razorpay-Signature` as HMAC-SHA256 over the **exact raw request bytes** before JSON parsing;
- require `x-razorpay-event-id` as stable delivery identity;
- use the configured webhook secret, not any secret from the payload;
- retain the exact raw body plus relevant webhook headers in the raw journal envelope;
- exact replay of one event ID/body is idempotent;
- same event ID with a different body fails closed through the journal conflict contract;
- webhook ordering is not assumed.

The payment transition is determined by the signed top-level webhook event name, not by the current `payment.entity.status` snapshot.

## Payment webhook normalization

Canonical `PaymentEvent` fields:

- `source_event_id` = `x-razorpay-event-id`;
- `payment_id` = payload payment entity ID;
- `order_id` = provider order ID when present;
- `kind` = top-level event mapping;
- `amount`/`currency` = payment entity authoritative fields;
- `occurred_at` = top-level webhook `created_at` timestamp;
- `received_at` = ReFlow receipt timestamp;
- error code/reason = payment entity error fields when present.

A `payment.authorized` webhook remains an AUTHORIZED transition even if its embedded payment snapshot already says `captured`.

## Settlement Recon normalization

Gate 15 consumes provider-shaped Settlement Recon items directly.

Required semantics:

- `type` in payment/refund/transfer/adjustment;
- `entity_id` prefix must agree with `type`;
- `settlement_id` must be a standard `setl_...` settlement ID;
- `debit`, `credit`, `amount`, `fee`, `tax` are integer paise/subunits and non-negative;
- a financially relevant row must have exactly one direction: debit xor credit;
- `settled` must be true before the row is admitted to a completed settlement composition;
- `settled_at` must be present and timestamp-valid;
- current canonical currency support remains INR.

Authoritative settlement effect:

```text
settlement_effect = credit - debit
```

Gate 15 never reconstructs provider settlement effect using the synthetic fixture rule `gross - fee - tax`.

Canonical principal/gross amount:

- payment: `+amount`;
- refund: `-amount`;
- transfer/adjustment: sign follows provider debit/credit direction.

Provider-reported `fee` and `tax` are retained as deterministic diagnostic fields. They are not added together to reconstruct `settlement_effect`; provider documentation may expose tax as a component of the reported fee.

`occurred_at` for the settlement contribution is the provider `settled_at` timestamp. The raw item retains the underlying provider `created_at` separately.

## Stable recon identity

Provider recon reports do not expose the existing synthetic `recon_id` contract.

Gate 15 creates a deterministic `ReconEntryId` from the provider account context plus stable provider economic identity, including settlement ID, entity type and entity ID.

The raw `SourceLink.source_record_id` remains provider-shaped and can differ from the canonical `ReconEntryId`. The compilation digest binds both identities.

## Settlement normalization

A standard settlement is canonicalized only when provider state proves it is `processed`.

For `settlement.processed` webhook:

- settlement ID must be `setl_...`;
- entity must be `settlement`;
- amount and UTR are normalized from the embedded entity;
- Razorpay's documented standard settlement shape omits `currency`, so currency comes from explicit account context (and any supplied provider currency must agree);
- canonical `processed_at` uses the signed webhook event timestamp.

The resulting `Settlement` does **not** prove bank receipt. Gate 8 remains the independent bank-evidence authority.

Instant Settlement IDs (`setlod_...` / payout `setlodp_...`) are not coerced into the standard `Settlement` model in Gate 15.

## Provider API settlement entity

A fetched standard settlement entity with status `processed` may be normalized when no webhook is being consumed. The raw provider `created_at` is retained and schema-validated as API entity timing, but canonical `processed_at` is the ReFlow `received_at` observation time: that is the earliest fact this API read actually proves the entity was already processed. The integration must not reinterpret provider `created_at` as processing time or bank-credit time.

The preferred Gate 15 causal fixture for a processing transition remains the signed `settlement.processed` webhook.

## Provenance-preserving compilation

Gate 15 emits journal-backed `CanonicalBatch` fragments that are compatible with the existing Money Graph and Gates 7–14.

It must not add a provider-specific matching/proof path.

For each canonical provider fact, the batch binds:

```text
raw provider source identity
raw immutable SourceEnvelopeId
canonical financial identity
```

Changing raw provider evidence changes compilation identity.

## Connected-account evidence non-claim

The connected read-only merchant account currently exposes payment records but no usable settlement or settlement-reconciliation rows for the inspected period. No private account payment payload is checked into this repository.

Gate 15 therefore makes no real Test Mode settlement accuracy claim at this checkpoint. Official-provider documentation fixtures are explicitly labelled `PROVIDER_DOC_FIXTURE`.

## Gate 15 acceptance tests to write before implementation

1. valid payment webhook signature over exact raw bytes is accepted;
2. invalid signature fails before canonicalization;
3. signed raw webhook bytes and event/signature headers are retained in the journal;
4. webhook account mismatch fails closed;
5. webhook event ID is required;
6. exact duplicate webhook delivery is idempotent;
7. same event ID with different raw body is retained as conflicting evidence and fails closed;
8. `payment.authorized` maps to AUTHORIZED even when entity snapshot says captured;
9. out-of-order failed/captured delivery remains deterministic through the existing payment reducer;
10. payment event timestamp comes from top-level webhook event time, not entity creation time;
11. provider-doc payment recon sample normalizes effect from credit/debit without synthetic arithmetic;
12. provider-doc refund recon sample normalizes debit as negative effect;
13. provider-doc transfer sample proves fee/tax are not double-counted into settlement effect;
14. provider-doc adjustment sample normalizes direct credit effect;
15. both debit and credit positive is rejected;
16. zero debit and zero credit for a financially relevant row is rejected;
17. entity/type prefix mismatch is rejected;
18. unsettled recon item is retained raw then rejected from canonical composition;
19. malformed provider recon item is journaled before semantic normalization failure when identity is recoverable;
20. provider recon raw identity deterministically binds to canonical `ReconEntryId` through `SourceLink`;
21. processed settlement webhook normalizes standard settlement amount/UTR/timestamp;
22. settlement webhook account mismatch fails closed;
23. non-processed/unsupported settlement event is rejected rather than canonicalized;
24. Instant Settlement ID is rejected by the standard settlement compiler;
25. `PROVIDER_DOC_FIXTURE` origin is preserved and `SYNTHETIC` is rejected by Gate 15 provider APIs;
26. provider-shaped recon + settlement fixture can feed the existing Gate 7 proof path with exact `credit-debit` arithmetic;
27. payment webhook duplicate/order permutation cannot manufacture new canonical financial value;
28. direct canonical output remains journal-backed; bypassing raw evidence is not exposed by the public provider API;
29. production Gate 15 module imports no simulator truth;
30. fixture/source labels never claim `REAL_TEST_MODE` unless explicitly supplied by a real test-mode context.

Hardened implementation coverage added after the frozen first pass:

31. documented standard settlement webhook shape without `currency` uses explicit account currency;
32. processed settlement API entity is journal-first and uses observation time as canonical processed-state time;
33. unprocessed settlement API entity is retained raw then rejected;
34. malformed settlement API `created_at` is retained raw then rejected;
35. malformed/out-of-range webhook and recon timestamps cannot bypass raw journal retention;
36. Gate 15's public compile surface remains journal-first after adding the API settlement compiler.
37. provider-shaped recon + settlement + independent bank evidence reaches the unchanged Gate 9 full-proof ledger;
38. all safely identifiable recon rows are journaled before any row's semantic normalization can fail;
39. a recon identity conflict is retained without preventing later identifiable rows from the same response being journaled;
40. a signed webhook with a non-`event` outer envelope is retained then rejected;
41. a signed webhook missing the expected entity in `contains` is retained then rejected.

## Deferred from Gate 15

- durable credential storage;
- authenticated application user identity;
- webhook HTTP server/framework;
- scheduled recon polling;
- generic OAuth/merchant onboarding;
- bank connector implementation;
- explicit Instant Settlement proof topology;
- production settlement persistence;
- AI investigation;
- UI;
- scale benchmark.

## Admission rule for Gate 16

Gate 15 is complete only when real provider-shaped inputs are journal-first, explicitly origin-labelled, deterministically normalized into the existing proof kernel, and no synthetic field rule is presented as Razorpay production semantics.

Only then may the bounded Exception Investigation Agent begin.
