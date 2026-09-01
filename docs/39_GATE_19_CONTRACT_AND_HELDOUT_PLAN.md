# Gate 19 Contract and Held-Out Plan — Final Failure Campaign + Submission

## Status

Gate 19 starts only after final Gate 18 metadata `main` is green. The Gate 18 product merge is `8d9bcabeb345c921ca2fe554c566597f1830a1b8`; the post-merge metadata SHA is `601f14835d177ea538f61502680527d70069f092` and its exact CI is green before this branch is created.

This document and `data/eval/gate19/heldout_manifest.json` are frozen **before any Gate 19 held-out case is executed**.

## Official bar rechecked on 2026-09-01

Razorpay Track 04 asks for one finance-ops loop across a 50+ record synthetic batch, with throughput, measured accuracy and an honest exception list. Submission requires a public repository, five-minute pitch video and architecture.

Gate 19 therefore optimizes for reproducible evidence, not a new feature spree.

## 1. No post-outcome tuning rule

The existing Gate 11 truth scorer and candidate systems are the frozen judge for the primary held-out run. Their SHA-256 hashes are stored in the held-out manifest.

After the first held-out execution:

- no threshold/scorer/candidate change may be used to improve the same held-out result;
- if a genuine product defect is fixed after observing a held-out failure, that result remains published and a **new manifest version with new precommitted seeds** is required for any post-fix benchmark;
- no case may be removed because it looks bad;
- source-rejected cases may not disappear from denominators silently.

## 2. Frozen corpora

### Primary held-out benchmark

12 precommitted cases × 64 settlements = **768 settlements**:

- 4 clean cases;
- 8 `reconciliation_adversarial` cases.

All systems see identical observed evidence per case:

- B0 naive 1:1;
- B1 grouped exact;
- B2 fuzzy threshold;
- ReFlow Core.

The primary headline denominator is all 768 requested settlements. A source-rejected primary case contributes zero automatic matches rather than being deleted from the denominator.

### Safety failure campaign

4 precommitted cases × 64 settlements = **256 settlements** using `source_schema_adversarial`.

This profile is intentionally designed to exercise fail-closed source handling (malformed date/schema rename/rupee-paise/sign traps) and is reported separately from headline match rate. Its purpose is to test quarantine/safe failure, not to pretend malformed schemas are normal reconciliation inputs.

## 3. Headline metrics

For every system and the primary corpus publish raw counts plus ratios:

1. requested settlements;
2. evaluated settlements;
3. source-rejected cases/settlements;
4. auto-reconciled;
5. true auto-reconciled;
6. false auto-reconciled;
7. safe match rate = true auto-reconciled / all requested settlements;
8. auto-match precision = true auto-reconciled / auto-reconciled;
9. silent false auto-match rate = false auto-reconciled / auto-reconciled;
10. unresolved requested settlements;
11. settlement amount correctness;
12. composition amount correctness;
13. composition edge TP/FP/FN and precision/recall;
14. bank edge TP/FP/FN and precision/recall;
15. exact emitted status counts;
16. wall-clock throughput with hardware/runtime disclosure.

No percentage is published without numerator and denominator.

## 4. Honest exception list

For ReFlow Core, the final artifact must include every primary non-green decision with:

- held-out case ID;
- settlement ID;
- status;
- reason codes;
- settlement/composition/bank amounts;
- exact composition/bank evidence IDs available to the candidate decision.

No LLM-generated explanation is part of the truth score.

## 5. Safety campaign result

The safety corpus publishes per case:

- corruption manifest;
- whether ingestion/evaluation rejected the source;
- rejection type/message;
- raw envelopes retained before failure;
- whether any candidate decision was emitted.

The desired property is fail-closed behavior with retained evidence, not a high match rate.

## 6. Failure campaign beyond the benchmark

Gate 19 must also rerun/record representative regressions for:

- source outage / late source;
- Gate 14 case carry-forward and economic supersession;
- Gate 16 provider outage;
- prompt-like source text / hallucinated citation / wrong numeric claim;
- denied unsafe tool/action;
- PostgreSQL duplicate/conflict/restart/CAS behavior;
- SPA direct-route/API-boundary behavior (F-0082);
- exact reviewer command path (F-0083).

These tests are evidence that known failure classes remain fixed; they are not substituted for the held-out corpus.

## 7. Scale evidence

Gate 17's checked-in 50/1k/10k artifacts remain the scale evidence unless Gate 19 changes proof-core performance semantics. Do not rerun a larger tier merely for a bigger headline number.

The final submission must disclose the exact Oracle hardware/runtime and distinguish in-memory proof throughput from fine-grained PostgreSQL write throughput.

## 8. AI evidence

If a real model API key is available, live adapter/investigation evaluation must use a separately frozen corpus and report cost/latency/validity. If no key is available, publish the deterministic/fake-transport safety evidence and explicitly state that no live-model quality number was measured.

AI remains optional to deterministic reconciliation truth.

## 9. Provider evidence

The connected Razorpay account previously exposed no settlement/recon corpus. Gate 19 must not promote public Razorpay documentation fixtures into `REAL_TEST_MODE` evidence. If no authenticated settlement/recon evidence becomes available, preserve that limitation.

## 10. Submission artifacts

Gate 19 should produce, from code rather than manual arithmetic:

- `data/eval/gate19/final-heldout.json`;
- `data/eval/gate19/failure-campaign.json` or equivalent reproducible regression record;
- `EVALUATION.md` generated from verified artifacts;
- final README metrics/limitations grounded in those artifacts;
- architecture/demo narrative aligned to the shipped Gate 18 UI;
- five-minute pitch script/storyboard;
- fresh-clone/reviewer verification commands;
- secret scan and public-repo hygiene check.

## 11. Definition of done

Gate 19 is complete when:

1. frozen manifest/scorer policy predates held-out execution;
2. final artifact self-verifies from raw decisions/truth;
3. baseline and ReFlow metrics are generated from identical cases;
4. every ReFlow exception is inspectable;
5. source-rejected cases are visible and cannot improve the denominator by disappearing;
6. the safety failure campaign is recorded;
7. final static/PostgreSQL/frontend CI remains green;
8. README/EVALUATION/limitations contain no unsupported claim;
9. public submission assets are reproducible and do not expose secrets;
10. unresolved limitations are stated plainly.
