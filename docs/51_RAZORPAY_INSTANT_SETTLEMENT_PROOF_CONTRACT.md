# Gate 51 — Razorpay Instant Settlement payout proof contract

**Started:** 2026-09-04
**Base `main`:** `20a754be4aeb6ed85a13150918f2a43d2cc00dbb`
**Working branch:** `hardening/instant-settlement-proof`
**Status:** merged and closed

## Purpose

Gate 51 closes the provider-semantic gap intentionally left by Gate 8 and Gate 15.
Standard Razorpay settlements remain `setl_...` entities with the existing one-settlement-UTR bank-proof rules.
Instant Settlements are modeled separately from documented provider evidence:

```text
settlement.ondemand parent        setlod_...
  -> settlement.ondemand_payout   setlodp_...
  -> payout UTR
  -> one bank credit
```

Multiple bank credits are valid for one Instant Settlement only when Razorpay provides distinct payout identities that bind those credits independently. ReFlow still never infers a split settlement from arbitrary same-amount, nearby-time, narration-similar or shared-UTR bank rows.

## Current Razorpay contract used

The current Razorpay Instant Settlement API documents:

- `https://razorpay.com/docs/api/settlements/instant/entity/`;
- `https://razorpay.com/docs/api/settlements/instant/fetch-with-id/`;

and specifies:

- parent entity `settlement.ondemand` with `setlod_...` identity;
- expanded `ondemand_payouts` collection;
- child entity `settlement.ondemand_payout` with `setlodp_...` identity;
- parent statuses `created`, `initiated`, `partially_processed`, `processed`, `reversed`;
- payout statuses `created`, `initiated`, `processed`, `reversed`;
- payout-level `initiated_at`, `processed_at`, `reversed_at`, `amount`, `amount_settled`, `fees`, `tax` and `utr`;
- `amount_settled` as payout amount minus the combined fee/tax deduction represented by `fees`;
- bounded collection acquisition through `/v1/settlements/ondemand/` with `expand[]=ondemand_payouts`.

Provider documentation is contract/reference evidence, not a claim that a real merchant Instant Settlement corpus has been validated.

## Additive domain boundary

Gate 51 adds typed identities:

- `InstantSettlementId` -> `setlod_...`;
- `InstantSettlementPayoutId` -> `setlodp_...`.

It also adds canonical `InstantSettlement` and `InstantSettlementPayout` records under `RAZORPAY_INSTANT_SETTLEMENT` provenance.

The standard types remain unchanged:

- `SettlementId` still requires `setl_...`;
- `BankReceiptProof` still requires exactly one bank entry for a proven standard settlement;
- Gate 9 standard settlement composition does not accept Instant Settlement entities.

`CanonicalBatch` carries the new collections additively. When both Instant Settlement collections are empty, the pre-Gate-51 compilation digest is unchanged so frozen standard evidence remains byte-compatible.

## Provider ingestion

`reflow.instant_settlement_integration` exposes the Gate 51 compiler without widening Gate 15's frozen `razorpay_integration.__all__` surface.

The compiler is journal-first:

1. retain the expanded parent provider entity;
2. validate that `ondemand_payouts` is an expanded collection;
3. retain every safely identifiable payout before semantic normalization;
4. reject duplicate payout identities in one collection;
5. normalize only from retained immutable evidence;
6. bind parent and payout canonical identities to their raw source envelopes.

An unexpanded parent is retained then rejected for proof use. A malformed child identity is retained when safely identifiable then rejected. Conflicting payload under one payout source identity remains a journal conflict.

## Payout-level bank proof

`prove_all_instant_settlement_receipts()` is separate from the standard Gate 8 bank proof.

A payout can be `PROVEN` only when all of these hold:

- payout status is `processed`;
- `processed_at` exists;
- payout UTR exists;
- `amount_settled` is positive;
- processed payout arithmetic satisfies `amount_settled + fees == amount`;
- the payout UTR is not reused by another explicit payout;
- exactly one bank entry uses that payout UTR;
- the bank entry occurs at or after payout processing;
- bank currency equals payout currency;
- bank amount equals payout `amount_settled`.

Otherwise the payout remains `WAITING`, `RESIDUAL`, `INCOMPLETE` or `CONTRADICTED` with explicit reason codes.

A payout-UTR reuse contradiction cites the sibling payout source envelope that creates the conflict. Duplicate bank rows under one payout UTR cite the conflicting bank envelopes.

## Parent proof

An Instant Settlement parent is `PROVEN` only when:

- it has at least one explicit payout;
- parent status is `processed`;
- every referenced payout exists and binds back to the exact parent;
- no orphan payout exists in the batch;
- every payout proof is `PROVEN`;
- sum of payout `amount_settled` values equals parent `amount_settled`;
- sum of proven bank credits therefore equals parent `amount_settled`.

The parent proof can legitimately contain multiple bank-entry IDs because each one is independently bound through a distinct provider payout identity.

## Acquisition boundary

`RazorpayAcceptanceClient.fetch_instant_settlements()` adds bounded read-only acquisition using:

- fixed Razorpay API origin;
- Basic auth supplied only through request headers;
- no redirects;
- response-byte limit;
- page/record limits;
- page size 100;
- `expand[]=ondemand_payouts` on every page;
- `skip` advancement with the existing fail-closed collection validator.

The existing standard-settlement real-data acceptance report is not silently redefined to include Instant Settlements.

## Compatibility requirements

Gate 51 must preserve:

- Gate 15 frozen public compile surface;
- all standard `setl_...` proof semantics;
- standard settlement UTR-reuse contradictions;
- existing compilation hashes for batches without Instant Settlement facts;
- reconciliation/control-plane source-account binding;
- frozen Gate 17 and Gate 19 artifacts;
- logical backup/PITR and production-readiness tests.

`RAZORPAY_INSTANT_SETTLEMENT` maps to the same Razorpay provider account as event, recon and standard-settlement evidence when a policy explicitly uses that source kind. Gate 51 does not make Instant Settlements mandatory for merchants that do not use the product.

## Reproduced implementation findings

Gate 51 preserved the following pre-merge failures in `FAILURE_LOG.md`:

- **F-0130** — first implementation accidentally widened Gate 15's frozen public compile API;
- **F-0131** — new Instant source kind was initially missing from reconciliation-scope provider-account mapping;
- **F-0132** — exact duplicate payout identities in one expanded response could otherwise collapse through journal idempotency;
- **F-0133** — processed payout arithmetic was initially under-constrained relative to the provider contract;
- **F-0134** — generic adapter schema initially advertised the provider-only Instant Settlement source kind.

Each finding has a regression or an existing compatibility guard.

## Local validation checkpoint

Before the final documentation/security pass, the exact Gate 51 tree passed:

- whole-repository Ruff;
- strict mypy across **77 source files**;
- **552 Python/PostgreSQL tests** with recovery drill enabled;
- TypeScript checking;
- React/Vitest **6/6**;
- Vite production build;
- frozen Gate 17 scale/persistence verification;
- frozen Gate 19 held-out/failure/summary verification and `EVALUATION.md` check;
- focused Instant/standard compatibility suite;
- Razorpay acceptance client **10/10**, including expanded Instant Settlement pagination;
- optimized Python (`python -O`) non-PostgreSQL suite: exit **0** with the expected pytest assertion warning;
- Bandit medium/high: **0 findings**;
- `pip-audit`: **0 known Python vulnerabilities**;
- npm production dependency audit: **0 vulnerabilities**;
- full npm dev audit: unavailable because the npm registry timed out on two bounded attempts; `web/package.json` and `web/package-lock.json` are unchanged from the green Gate 50 base;
- high-confidence production/docs credential scan: clean;
- production source hygiene scan: no TODO/FIXME/HACK, `eval`, `exec`, or `shell=True`;
- `git diff --check`: clean.

The local validation was followed by required repository closure:

- implementation commit: `fff20cf81f7e4cd1ba58a22469422b0331c168f4`;
- PR: **#42**;
- exact PR CI: **33848215642**, success with **552 tests**, strict mypy across **77 source files**, frontend **6/6**, production build, recovery drills and frozen Gate 17/19 verification;
- merge commit: `be0fcec57386f132452ba9d255b9cabee4a5bfbb`;
- exact merge-triggered `main` CI: **33850178698**, success with the same **552-test** recovery-enabled submission gate and frozen evidence checks.

No PR/main CI failure occurred in Gate 51.

## Explicit non-claims

Gate 51 does not claim:

- authenticated real/Test Mode Instant Settlement accuracy;
- that the currently connected Razorpay account contains any Instant Settlement rows;
- Instant Settlement webhook support;
- Instant Settlement recon-composition semantics inside the standard Gate 9 proof;
- fuzzy payout-to-bank matching;
- inferred grouping of arbitrary bank credits;
- Smart Settlement/RTGS-specific proof semantics beyond explicit payout evidence;
- production enablement of Razorpay Instant Settlements for the merchant account.

## Merge rule

The exact implementation head passed required PR CI, PR #42 merged without head movement, and the exact merge-triggered `main` CI passed. Gate 51 is closed.
