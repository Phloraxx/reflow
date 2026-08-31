# Messy Data and Connector Compiler

## Goal

Reconciliation systems rarely fail because someone forgot how to add two numbers. They fail because the inputs are inconsistent, ambiguous, changed without notice, encoded in incompatible units, or missing the identifiers the next system expects.

ReFlow should treat source integration as a product capability, not plumbing.

The proposed solution is an **AI-assisted Source Adapter Compiler**:

> Let AI understand an unfamiliar export once, then compile that understanding into a deterministic, versioned adapter that must pass financial and structural tests before it can process production data.

The runtime reconciliation path remains deterministic.

## Implemented Gate 12 contract

Gate 12 is now implemented. The supported operational path is journal-first and separates proposal quality from activation authority:

```text
raw rows
  -> immutable SourceEnvelope journal
  -> structural profile / exact schema fingerprint
  -> optional bounded AI AdapterSpec proposal
  -> deterministic compile + canonical sample validation
  -> REJECTED or NEEDS_REVIEW for first-seen schemas
  -> explicit operator review OR canonical-equivalent migration evidence
  -> approved adapter version
  -> compile retained journal payloads
  -> CanonicalBatch with raw->canonical SourceLinks
  -> existing Money Graph / proof pipeline
```

A financial control total can reject a wrong money mapping, but cannot by itself prove identifier/reference semantics. Therefore a first-seen AI proposal never auto-activates solely because it parses or its total matches. Automatic activation is limited to deterministic migration equivalence from an already approved adapter.

The optional OpenAI provider requires an explicit model, uses strict JSON-schema output with `store=false`, sends bounded/redacted samples, and has no capability to approve an adapter or assert financial truth.

---

## 1. Supported source classes

Buildathon priority:

1. Razorpay webhook JSON / fixture stream
2. Razorpay Settlement Recon API-shaped JSON/CSV
3. Razorpay settlement records
4. merchant/order CSV
5. bank statement CSV
6. generic CSV with unknown headings

Stretch only after the above is proven:

- XLSX import;
- PDF/text statement extraction;
- screenshot/table extraction;
- multi-gateway source packs;
- accounting exports.

Razorpay's own Agentic Platform already demonstrates screenshot-based reconciliation. ReFlow should **not** make OCR the main novelty. Its differentiator is the verified connector lifecycle and financial proof system.

---

## 2. Canonical source envelope and lineage

No unknown raw record goes directly into model inference or business logic. Gate 12 first stores each row as an immutable `SourceEnvelope` with source kind, stable raw source identity, receive time, schema version, payload hash and frozen payload. Conflicting payloads under the same raw identity are preserved before the journal fails closed.

After an adapter is approved, the canonical fact retains a `SourceLink` back to that exact envelope. Gate 12 required the lineage contract to distinguish:

```text
raw source identity       adapter-batch:<batch>:row:<n>
canonical identity        bank_... / order_... / recon_... / ...
raw evidence identity     src_...
```

Normalized Gate 4 fixtures often have the same raw and canonical ID, but unknown exports do not. `SourceLink` now preserves both identities while downstream proofs continue to resolve canonical identity -> raw envelope ID.

The canonical compilation digest includes the source links, so changing the raw/canonical lineage changes compilation identity.

---

## 3. Adapter specification

Instead of generating arbitrary Python, the model should generate a constrained declarative spec.

Example:

```yaml
adapter: bank_generic_v3
input:
  format: csv
  encoding: utf-8
  delimiter: ","
fields:
  transaction_reference:
    from: "Txn Ref"
    transform: trim
  occurred_at:
    from: "Value Dt"
    transform: date
    args:
      formats: ["DD/MM/YYYY", "DD-MM-YYYY"]
  credit_paise:
    from: "Amt Cr"
    transform: money
    args:
      unit: rupees
      locale: en-IN
  debit_paise:
    from: "Amt Dr"
    transform: money
    args:
      unit: rupees
      locale: en-IN
  narration:
    from: "Description"
    transform: trim
rules:
  - exactly_one_of: [credit_paise, debit_paise]
  - currency: INR
```

The compiler accepts only a finite transform vocabulary.

No generated `eval`, arbitrary Python, SQL or shell code.

---

## 4. Why AI belongs here

Column names are semantic and contextual:

```text
Amount
Amt
Value
Net Amt
Paid
Credit
Cr
Deposit
Settled Amt
Gross
```

A deterministic system cannot reliably infer every new schema without hard-coded aliases. An LLM is genuinely useful for:

- identifying likely semantic fields;
- interpreting abbreviations;
- recognizing date/reference/narration columns;
- proposing sign conventions;
- explaining uncertainty;
- mapping custom merchant exports to canonical concepts.

But semantic inference is a **proposal**, not financial truth.

---

## 5. Adapter compilation and approval pipeline

```text
retained raw journal rows
   ↓
Structural profiler
   ↓
Optional AI mapping proposal
   ↓
Typed AdapterSpec parser
   ↓
Static validation
   ↓
Finite deterministic transform plan
   ↓
Existing Gate 4 canonical adapter
   ↓
Sample/invariant validation
   ↓
Optional independent financial control
   ↓
REJECTED / NEEDS_REVIEW
   ↓
operator review OR safe migration equivalence
   ↓
APPROVED ADAPTER VERSION
```

### Structural profiler

Profiles exact and normalized column names, primitive type families, null/presence counts, uniqueness and bounded samples. Schema fingerprints do not include financial row values, but they do include exact source column names because deterministic adapter lookup is exact.

### AI proposal

The model sees the requested adapter contract, target fields, allowed transforms, structural profile and bounded/redacted sample rows. It returns only `AdapterSpec`. The caller fixes adapter ID/version/source kind/record kind, and a model that changes that contract is rejected.

### Static validation

The compiler rejects missing columns, unsupported targets/transforms, invalid source-kind↔record-kind pairings, and constants for authoritative money/ID/time fields. `CONSTANT` is restricted to narrow categorical fields.

### Sample execution

The proposed plan canonicalizes through the existing audited adapters. Parse errors, duplicate canonical identities, sign/unit violations, invalid timestamps and other canonical contract violations reject the proposal.

### Financial controls

When an independent source total exists, exact integer-paise totals and row counts can reject a 100x unit error. A passing total does **not** establish identity/reference semantics and therefore does not authorize a first-seen proposal.

### Authorization

First-seen valid proposals remain `NEEDS_REVIEW`. Operator approval creates typed approval evidence bound to the exact adapter ID/version/schema. Automatic activation is limited to a migration whose old/new fixtures reproduce identical canonical financial facts. Validation and authorization are separate contracts.

---

## 6. Confidence without hand-waving

Avoid using one opaque model confidence score as approval criteria.

Use an approval checklist:

```text
HEADER_MAPPING_VALID       yes/no
SAMPLE_PARSE_RATE          numeric
REQUIRED_FIELDS_PRESENT    yes/no
UNIT_INVARIANTS_PASS       yes/no
CONTROL_TOTALS_PASS        yes/no/not_available
DATE_RANGE_PLAUSIBLE       yes/no
IDENTIFIER_CARDINALITY_OK  yes/no
SIGN_RULES_UNAMBIGUOUS     yes/no
```

A connector is safe because checks pass, not because the LLM says `0.97 confidence`.

---

## 7. Schema fingerprints

Every ingestion batch gets a deterministic schema fingerprint derived from properties such as:

- exact source column names;
- normalized column names;
- inferred primitive type families;
- declared adapter/record contract outside the structural fingerprint where routing requires it.

The fingerprint does **not** hash sensitive row data.

Purpose:

- detect previously unseen schema;
- recognize known source versions;
- trigger drift review before processing.

---

## 8. Schema drift states

Suggested states:

```text
KNOWN_SCHEMA
BENIGN_DRIFT
REQUIRES_MIGRATION
BREAKING_DRIFT
UNRECOGNIZED_SOURCE
```

Examples:

### Benign

- column order changed;
- new unused column added.

### Requires migration

- `Settlement UTR` renamed to `Bank Reference`;
- date format changes;
- zero values start appearing as `-`.

### Breaking

- debit/credit semantics reversed;
- amount unit changes;
- required identifier disappears;
- a previously unique field becomes non-unique.

Breaking drift quarantines the batch.

---

## 9. Adapter migration workflow

When drift is detected:

```text
Existing Adapter v4
        │
        ├── old fixture corpus
        └── new failing sample
                 ↓
       AI proposes Adapter v5
                 ↓
       deterministic compile
                 ↓
      replay old + new fixtures
                 ↓
      canonical financial diff
                 ↓
 MIGRATION_EQUIVALENCE / reject v5
```

Critical rule:

> A new adapter must not fix today's file by breaking historical compatibility invisibly.

The diff report should show changed canonical output field-by-field.

---

## 10. Source quality scoring

ReFlow can compute a deterministic quality profile for each source instance.

Possible measures:

- identifier completeness;
- unique-key collision rate;
- timestamp completeness;
- parse error rate;
- amount null rate;
- control-total availability;
- late-arrival distribution;
- schema drift frequency.

This becomes useful evidence for matching policies.

Example:

```text
Bank CSV A
- UTR coverage: 99.8%
- amount validity: 100%
- timestamp validity: 100%
- duplicate refs: 0.01%
- drift: stable 43 days
```

Source quality is not the same as a financial match confidence; it describes the reliability of the source feed.

---

## 11. Messy narration handling

Narration is useful but dangerous.

Normalization can deterministically:

- uppercase/lowercase consistently;
- normalize whitespace;
- strip common punctuation;
- extract known reference-like tokens;
- tokenize alphanumeric segments.

Embedding/fuzzy similarity may rank candidates only after stronger partitioning.

Never auto-reconcile based only on semantic narration similarity.

Bank narration is also untrusted data. If passed to an LLM, delimit and label it as data so prompt-like text in a narration cannot become an instruction.

---

## 12. File-level quarantine

One malformed row should not necessarily kill a 100,000-row import, but a systemic schema mistake should.

Use two levels:

### Record quarantine

For isolated parse failures:

- retain row;
- mark `SOURCE_RECORD_INVALID`;
- continue batch if source-level invariants remain safe.

### Batch quarantine

For systemic uncertainty:

- unknown amount unit;
- sign ambiguity;
- missing required identity field across the file;
- schema drift likely to reinterpret values;
- control totals materially fail.

In these cases, stop before financial reconciliation.

---

## 13. Low-volume experience

The connector compiler is especially valuable for small operators.

Flow:

1. drag merchant CSV;
2. drag Razorpay recon export;
3. drag bank CSV;
4. ReFlow recognizes or proposes mappings;
5. operator sees a compact mapping preview;
6. deterministic checks pass;
7. reconciliation runs.

No engineering integration required.

The first-run setup should feel like teaching ReFlow a file format, not configuring an ETL pipeline.

---

## 14. High-volume experience

At scale, interactive inference is removed from the hot path.

- approved adapter versions are cached/versioned;
- batches are schema-fingerprinted before parse;
- parsing is vectorized/streamed;
- unseen drift is quarantined immediately;
- AI is invoked only for new/drifted schema proposals;
- canonical events are emitted to the same downstream reconciliation core.

Thus model usage scales with **number of source formats/drifts**, not number of transactions.

This is economically and operationally important.

---

## 15. Security and authority boundaries

The adapter model:

- never receives repository credentials or write tools;
- never executes generated code;
- only selects from the finite `AdapterSpec` vocabulary;
- receives bounded sample rows with deterministic redaction for obvious address-like values, long numeric identifiers and known secret-token patterns;
- treats free-text source content as untrusted data;
- cannot choose a different adapter identity/source contract than the caller requested;
- cannot approve a first-seen adapter;
- cannot create reconciliation proof.

The redaction layer is heuristic and is **not** a production DLP guarantee. Real customer data is outside the public benchmark scope.

The deterministic compiler, explicit operator-review transition and migration-equivalence validator own activation.

---

## 16. Evaluation

Create a connector benchmark independent from reconciliation accuracy.

Dataset families:

- canonical clean;
- renamed headers;
- reordered columns;
- alternate date formats;
- rupee/paise trap;
- credit/debit split vs signed amount;
- blank and `-` null styles;
- commas in Indian-number formatting;
- duplicate identifiers;
- missing required column;
- malicious/prompt-like narration;
- schema drift between batch N and N+1.

Metrics:

```text
adapter proposal validity
compile success rate
canonical field accuracy
unit/sign error rate
unsafe adapter activation rate
schema drift detection recall
false drift alarm rate
rows/sec after adapter is compiled
LLM calls per 1M rows
```

Gate 12 evaluates two surfaces separately: proposal semantic quality and authorization safety. The checked-in development proposal corpus has 11 cases (7 correct reviewable previews, 4 correct rejections), while the migration corpus has 3 cases (1 safe automatic activation, 2 correct unsafe rejections, 0 unsafe activations). These are development regression results, not a live-model accuracy claim.

The migration benchmark makes the zero-unsafe-activation target non-vacuous by exercising a real automatic activation path. The general proposal benchmark can still count a wrong semantic preview even when the safety layer correctly keeps it out of production.

---

## 17. Why this is a strong Buildathon feature

This feature gives ReFlow meaningful AI that is:

- visibly useful;
- difficult to replace with a static rule list;
- bounded;
- testable;
- separate from financial truth;
- relevant to small merchants and enterprises;
- reusable for future connectors.

The demo can show an unfamiliar `weird_bank_export.csv` being understood and compiled, followed by the exact same reconciliation proof engine used for a known source.

That is a stronger story than “we sent the rows to Gemini and asked which ones matched.”
