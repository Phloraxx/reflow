# ReFlow Final Evaluation

> Generated from checked-in, self-verifying artifacts. Do not hand-edit metric values.

## Evaluation contract

The Gate 19 held-out seeds were committed before first execution. The existing Gate 11 scorer and candidate systems were frozen by SHA-256 in `data/eval/gate19/heldout_manifest.json`. The first v1 held-out result is preserved unchanged in `data/eval/gate19/final-heldout.json`.

- Primary corpus: **12 cases / 768 settlements / 87,364 observed records**.
- Mix: 4 clean cases and 8 reconciliation-adversarial cases; every case has 64 settlements.
- Safety corpus: **4 source-schema adversarial cases** reported separately from headline reconciliation metrics.
- Held-out artifact digest: `9f544fc298a64b7ad55537a55a8d7be853ba76b17588de7277ed0a59ac50f53e`.
- Failure-campaign artifact digest: `75ae650eacd98c062d4cd944594c07c322b3a55b7613491ae776067e17d7bb38`.

## Primary held-out result

`Safe match rate` uses all requested settlements as the denominator. `Auto-match precision` asks whether an automatic green decision was actually correct. `Truth-reconciled recall` measures true automatic matches against settlements that are reconciled in hidden truth; corrupted/missing observations can legitimately lower this because ReFlow fails closed rather than guessing.

| System | Auto matched | True auto | False auto | Safe match rate | Auto-match precision | Truth-reconciled recall | Silent false-match rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0_naive_1to1 | 0/768 | 0 | 0 | 0.00% | n/a | 0.00% | n/a |
| B1_grouped_exact | 512/768 | 512 | 0 | 66.67% | 100.00% | 82.05% | 0.00% |
| B2_fuzzy_threshold | 521/768 | 512 | 9 | 66.67% | 98.27% | 82.05% | 1.73% |
| ReFlow_Core | 512/768 | 512 | 0 | 66.67% | 100.00% | 82.05% | 0.00% |

### What the headline means

ReFlow automatically reconciled **512/768 (66.67%)** settlements. All **512/512** automatic matches were correct, so the frozen corpus produced **zero silent false auto-matches**.

The fuzzy baseline auto-matched 521 settlements, but 9 were wrong (1.73% silent false-match rate). ReFlow deliberately leaves those cases unresolved instead of buying coverage with incorrect financial truth.

The strong grouped-exact baseline has the same true auto-match count (512) and zero false auto-matches. ReFlow does **not** claim a recall win over that baseline. Its added value is exact provenance validation, typed residual/contradiction states, immutable proof versions, run-level controls, persistent cases, bounded investigation and the operator control tower.

### Edge evidence

| System | Composition edge P / R | Bank edge P / R |
|---|---:|---:|
| B0_naive_1to1 | n/a / 0.00% | 96.08% / 59.91% |
| B1_grouped_exact | 99.93% / 99.93% | 100.00% / 85.49% |
| B2_fuzzy_threshold | 99.93% / 99.93% | 98.35% / 85.49% |
| ReFlow_Core | 99.96% / 99.93% | 100.00% / 85.49% |

### ReFlow by profile

| Profile | Settlements | Truth reconciled | Auto matched | Precision | Truth-reconciled recall | Unresolved |
|---|---:|---:|---:|---:|---:|---:|
| clean | 256 | 208 | 208 | 100.00% | 100.00% | 48 |
| reconciliation_adversarial | 512 | 416 | 304 | 100.00% | 73.08% | 208 |

## Honest ReFlow exception list

The primary corpus produced **256 non-green ReFlow decisions**. Status counts: `contradicted`=8, `residual`=78, `unresolved`=170.

Reason-code occurrences can overlap because one exception may have more than one deterministic reason:

- `BANK:BANK_RECEIPT_NOT_OBSERVED` — 173
- `BANK:BANK_AMOUNT_MISMATCH` — 64
- `COMPOSITION:SETTLEMENT_COMPOSITION_RESIDUAL` — 15
- `BANK:SAME_AMOUNT_NOT_IDENTITY` — 11
- `COMPOSITION:DUPLICATE_ECONOMIC_ROW` — 8

The complete machine-readable exception list—including settlement ID, status, reason codes, amounts, recon evidence IDs and bank evidence IDs—is stored under `primary.reflow_exceptions` in `data/eval/gate19/final-heldout.json`. No exception was manually removed.

## Source-schema safety campaign

All **4/4** frozen source-schema adversarial cases failed closed before candidate decisions, with **0 candidate decisions emitted**. Each rejection retained thousands of raw envelopes before canonical interpretation failed.

This safety corpus contains malformed-date, schema-rename, rupee/paise and sign traps. It is intentionally reported separately from the headline match-rate denominator.

## Regression failure campaign

The final regression campaign passed **12/12** representative failure checks with zero failures. It covers source completeness, case continuity/supersession, model outage, prompt injection, hallucinated evidence, tool-scope denial, PostgreSQL conflict/restart/CAS semantics, SPA routing and source-data minimization.

## Throughput / scale evidence

The frozen four-system held-out campaign processed 768 settlements in 26.181s of recorded primary-case wall time (29.33 settlements/s). This includes world observation, four candidate systems and scoring, so it is **not** presented as ReFlow proof-core throughput.

For proof-core scale, the independently verified Gate 17 10k clean artifact processed **10,000 settlements / 1,203,220 raw rows** with a proof-pipeline rate of **206.97 settlements/s**, total runtime **267.56s**, and peak process RSS about **3.18 GiB** on the disclosed 4-vCPU aarch64 Oracle VM.

The separate fine-grained PostgreSQL durability benchmark measured about **76.1 cold source writes/s** and **90.2 cold immutable-artifact writes/s**. It is a durability reference, not a bulk-ingestion throughput claim.

## AI and real-provider evidence

No OpenAI/AI provider key was configured on the final Oracle evaluation host, so ReFlow makes **no live-model Gate 16 quality/cost/latency claim**. Gate 16 safety and protocol behavior is covered by deterministic/fake-transport tests and the final failure campaign.

No Razorpay API key was configured on the final Oracle evaluation host, and the earlier authenticated connected-account check exposed no settlement/recon corpus. ReFlow therefore makes **no REAL_TEST_MODE settlement accuracy claim**. Provider-document fixtures remain explicitly labelled as documentation fixtures.

## Reproduce / verify

```bash
python -m reflow.evaluation.final_campaign --manifest data/eval/gate19/heldout_manifest.json --verify data/eval/gate19/final-heldout.json
python -m reflow.evaluation.failure_campaign --verify data/eval/gate19/failure-campaign.json
python -m reflow.evaluation.scale_runner --verify data/eval/gate17/scale-10000-clean.json
python -m reflow.evaluation.persistence_runner --verify data/eval/gate17/postgres-1000-cold-warm.json
python -m reflow.evaluation.final_report --check EVALUATION.md
```

Re-running the held-out command is possible, but the checked-in v1 result is the **first run** and remains the submission result. A product/scorer change after seeing v1 would require a newly frozen seed manifest rather than overwriting v1.

## Non-claims

- This is synthetic/adversarial evaluation, as requested by Track 04; it is not merchant production data.
- 66.67% is a conservative safe automatic match rate over all requested settlements, **not** an accuracy percentage.
- The hidden-truth auto-match precision on v1 is 100% (512/512); truth-reconciled recall is 82.05% (512/624).
- ReFlow does not claim to outperform B1 grouped-exact on auto-match recall in this corpus.
- No 100k/1M scale, HA, production SLO, live-model accuracy, or real Razorpay settlement-accuracy claim is made.
