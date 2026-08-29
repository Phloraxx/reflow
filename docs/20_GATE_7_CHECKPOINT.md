# Gate 7 Checkpoint — Settlement Composition Proof

**Date:** 2026-08-29  
**Branch:** `build/phase-7-9-proof-engine`

This checkpoint freezes the deterministic foundation after the second independent implementation audit.

## Gate 7 is allowed to claim

For the current normalized fixture contract, ReFlow can deterministically determine whether supplied settlement recon evidence forms a valid settlement composition proof.

A proven composition requires:

- journal-backed settlement evidence;
- journal-backed recon evidence;
- exact raw-envelope provenance through the Money Graph;
- one currency;
- admissible temporal ordering;
- unique, non-conflicting economic identity ownership;
- no duplicate economic source rows;
- exact signed arithmetic equal to settlement amount;
- no unresolved proof reason.

## Gate 7 is not allowed to claim

It does not prove:

- bank receipt;
- full payment-to-bank reconciliation;
- production Razorpay Settlement Recon semantics;
- production persistence;
- final benchmark accuracy or throughput;
- AI correctness;
- production readiness.

Those remain later gates.

## Merge rule

This checkpoint may merge only with a green exact-head CI run covering Ruff, strict mypy and pytest.

Gate 8 must start from the merged Gate 7 checkpoint, not from an unreviewed continuation branch.
