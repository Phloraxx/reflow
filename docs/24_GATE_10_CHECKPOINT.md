# Gate 10 Checkpoint — Bounded Residual Solver

**Date:** 2026-08-31  
**Branch:** `build/gate-10-residual-solver`  
**Audited code head:** `41448a4e9011778a2c06aa3f2f31ba286173cb9e`  
**Status:** implementation green; final documentation-head CI and PR merge still required.

---

## 1. Purpose

Gate 10 explains **non-zero residuals that already exist in an immutable Gate 9 proof**. It does not search for a way to turn an unresolved settlement green.

The central safety rule is:

> **Arithmetic fit is a hypothesis, never financial proof.**

Gate 10 cannot mutate Gate 7 composition truth, Gate 8 bank truth or Gate 9 reconciliation status. New authoritative evidence must flow through those gates and create a new Gate 9 proof version.

---

## 2. Implemented flow

```text
ReconciliationProofVersion
        |
        +--> non-zero composition residual
        |          or
        +--> non-zero bank residual
                   |
                   v
             ResidualTarget
                   |
                   v
        ResidualCandidateIndex
                   |
         typed candidate evidence
                   |
                   v
        bounded deterministic search
                   |
                   v
       ResidualExplanation(HYPOTHESIS)
```

The public solver does not accept hidden simulator truth, caller-constructed candidate sets or invented source rows. `solve_residual()` derives candidates from the supplied proof and its exact canonical batch; the raw candidate-set search is a private unit-test seam.

---

## 3. Residual targets

`ResidualTarget` is bound to:

- one `SettlementId`;
- one exact `ProofVersionId`;
- one scope (`COMPOSITION` or `BANK`);
- one non-zero integer-paise `Money` value.

Targets are derived only from the embedded Gate 7/Gate 8 residuals in `ReconciliationProofVersion`.

A zero residual does not create a Gate 10 target.

---

## 4. Candidate contract

A `ResidualCandidate` is a deterministic, raw-provenance-backed **hypothesis input**. Its identity binds:

- target settlement;
- exact proof version;
- residual scope;
- candidate kind;
- source entity identity;
- amount and currency;
- raw `SourceEnvelopeId` set;
- blocked/admissible disposition;
- normalized reason codes.

Changing the proof version, disposition, reason codes, amount or provenance changes/invalidates the candidate identity.

Current candidate kinds are intentionally narrow:

1. `UNMATCHED_BANK_CREDIT`
   - positive amount-only bank evidence;
   - never bank identity proof;
   - rows already identified to another settlement are blocked;
   - rows occurring before settlement processing are blocked.
2. `BLOCKED_RECON_COMPONENT`
   - settlement-local recon evidence excluded by Gate 7;
   - useful for forensic arithmetic explanation;
   - always remains blocked evidence.

---

## 5. Explanation contract

`ResidualExplanation` embeds the bounded candidate objects that produced it rather than storing independently mutable candidate/source/reason metadata.

It derives:

- candidate IDs;
- explained amount;
- remaining residual;
- raw source-envelope union;
- whether blocked evidence is used;
- reason codes.

Published explanations must exactly close the residual numerically. Their only allowed state is:

```text
HYPOTHESIS
```

Every exact hypothesis includes `NUMERICALLY_EXACT_HYPOTHESIS` and `NOT_FINANCIAL_PROOF`. Explanations containing blocked candidates additionally include `USES_BLOCKED_EVIDENCE`.

The same raw source envelope cannot be counted twice inside one explanation.

---

## 6. Deterministic bounded search

Gate 10 uses explicit deterministic limits:

```text
max_candidates
max_combination_size
max_nodes
max_solutions
```

A wall-clock timeout is deliberately not a correctness boundary because different hardware must not change the logical search result merely by running faster or slower.

The result explicitly reports:

- `candidate_space_truncated`;
- `search_budget_exhausted`;
- `solution_limit_reached`.

These flags prevent a bounded result from being misrepresented as an exhaustive search.

`solution_limit_reached` means the configured output cap was reached. It is not a claim that additional explanations definitely exist.

---

## 7. High-volume shape

The first reference implementation could rescan the full bank feed per residual target. That does not scale with a large number of exceptions.

The audited path now builds one `ResidualCandidateIndex` per canonical batch and reuses it through `solve_all_residuals()`.

The index contains:

- bank rows ordered by currency and amount;
- settlement-local recon rows;
- settlement ownership by UTR;
- raw source identity → envelope provenance;
- settlement metadata needed for causal checks.

This removes the avoidable `residual_count × full_bank_feed` enumeration pattern. Search work remains bounded to local candidate windows and the configured node budget.

This is an algorithmic shape claim, not a throughput claim. Measured rows/sec and memory numbers belong to the later benchmark harness.

---

## 8. Safety behavior demonstrated

The Gate 10 regression suite covers:

- composition residuals created by plausible but financially wrong recon evidence;
- amount-only bank candidates staying hypotheses rather than proof;
- late recon rows remaining blocked even when they close the residual exactly;
- exact two-candidate arithmetic combinations;
- deterministic node-budget exhaustion;
- wrong canonical-batch rejection;
- bank evidence identified to another settlement being blocked;
- target-scoped candidate identities;
- unbound candidate-index rejection;
- explicit solution-cap reporting;
- batch solving with one reusable index;
- duplicate proof-version rejection;
- candidate identity binding to proof version and disposition;
- explanation metadata derived from embedded candidates;
- pre-settlement bank evidence being blocked;
- duplicate candidate identity rejection;
- prevention of double-counting one raw envelope.

At audited code head `41448a4...`, GitHub Actions reported:

```text
Ruff:        pass
strict mypy: pass (20 source files)
pytest:      154 passed
```

The final documentation head must pass the same checks again before merge.

---

## 9. Failures discovered during Gate 10

The canonical failure history is preserved in `FAILURE_LOG.md`:

- **F-0033** — residual explanation state was implicit;
- **F-0034** — candidate identity did not bind full target/decision context;
- **F-0035** — bank evidence identified elsewhere initially looked admissible;
- **F-0036** — residual enumeration could rescan the full bank feed per target;
- **F-0037** — solution-cap truncation was not disclosed;
- **F-0038** — explanation metadata was not self-verifying;
- **F-0039** — pre-settlement amount-only bank evidence could appear admissible;
- **F-0040** — duplicate/overlapping raw evidence could be double-counted;
- **F-0041** — the public single-residual solver could accept caller-constructed candidate sets.

Mechanical CI findings also occurred while implementing the gate: import ordering, one reused loop variable caught by strict mypy, and one stale expected reason-code string in a regression. Those were corrected but are not promoted into financial failure IDs.

---

## 10. Explicit non-goals / limitations

Gate 10 does **not** currently claim:

- exhaustive hypothesis enumeration when any bound is reached;
- negative bank residual / over-credit explanation families;
- arbitrary bank debit/reversal semantics;
- Instant Settlement `setlod` / `setlodp` payout explanations;
- CP-SAT or unbounded subset solving;
- semantic AI-generated hypotheses;
- evidence fabrication;
- proof promotion;
- accounting writeback;
- production throughput or memory performance.

The current bank candidate feed remains the normalized settlement-credit fixture contract described in `LIMITATIONS.md`.

---

## 11. Why no CP-SAT yet

The reference solver is intentionally small and inspectable. Current Buildathon value comes from demonstrating:

1. exact residual arithmetic;
2. typed evidence provenance;
3. bounded deterministic search;
4. safe handling of ambiguity and blocked evidence;
5. measurable behavior against baselines.

A constraint solver is only justified later if the benchmark shows that bounded combination search cannot represent important residual cases within acceptable resource limits.

Adding CP-SAT before measurement would increase dependency and debugging surface without yet proving product value.

---

## 12. Gate 10 merge criteria

Gate 10 may merge only when:

- [x] residual targets come only from immutable Gate 9 proofs;
- [x] exact explanations cannot become proof;
- [x] candidate and explanation identities/provenance are self-consistent;
- [x] foreign-settlement and pre-settlement bank evidence is blocked;
- [x] duplicated/overlapping raw evidence cannot be double-counted;
- [x] candidate/search/result bounds are deterministic and visible;
- [x] public single/batch APIs derive candidates from the canonical proof batch;
- [x] high-volume API reuses one batch candidate index;
- [x] audited code-head Ruff/mypy/pytest are green;
- [ ] final documentation-head CI is green;
- [ ] PR-triggered CI is green;
- [ ] checkpoint is merged to `main` and merge-commit CI is green.

---

## 13. Next gate

After Gate 10 merges, **Phase 11 is the baseline evaluation harness**.

The benchmark must compare at least:

```text
B0 naive 1:1
B1 strong grouped deterministic
B2 fuzzy threshold
ReFlow Core
```

It must use hidden financial truth only in the scorer, never in candidate engines, and must prove the harness can detect at least one intentionally wrong implementation before any headline metric is trusted.

AI remains blocked until deterministic baseline/evaluation evidence exists.
