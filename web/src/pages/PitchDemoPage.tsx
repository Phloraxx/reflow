import { useEffect, useMemo, useState } from 'react'
import { Activity, CheckCircle2, Database, LockKeyhole, Play, RotateCcw, Search, ShieldAlert, Unlock } from 'lucide-react'
import { StatusPill } from '../components/StatusPill'

type Dataset = {
  settlement_count: number
  profile: string
  world_seed: number
  observation_seed: number
  observed_record_count: number
  source_counts: Record<string, number>
  dataset_sha256: string
  truth_commitment_sha256: string
  corruption_count: number
}

type RunSummary = {
  elapsed_seconds: number
  proof_pipeline_seconds: number
  settlements_per_second: number
  graph_edges: number
  proof_count: number
  status_counts: Record<string, number>
  exception_count: number
  source_rejection: null | { error_type: string; message: string }
}

type Evaluation = {
  truth_settlement_count: number
  truth_reconciled: number
  reflow: EvalSystem
  fuzzy: EvalSystem
}

type EvalSystem = {
  system_name: string
  auto_reconciled: number
  true_auto_reconciled: number
  false_auto_reconciled: number
  unresolved: number
  precision: number | null
  recall: number | null
  silent_false_match_rate: number | null
  status_counts: Record<string, number>
}

type DemoStatus = {
  phase: string
  dataset: Dataset | null
  run: RunSummary | null
  truth_unlocked: boolean
  evaluation: Evaluation | null
  can_generate: boolean
  can_run: boolean
  can_unlock: boolean
}

type SettlementRow = {
  settlement_id: string
  status: string
  amount: { display: string }
  composition_status: string
  bank_status: string
  composition_components: number
  reason_codes: string[]
}

type ProofDetail = {
  settlement_id: string
  status: string
  settlement_amount: { display: string }
  observed_composition: { display: string }
  composition_residual: { display: string }
  bank_observed: { display: string }
  bank_residual: { display: string }
  settlement_utr: string | null
  reason_codes: string[]
  components: Array<{
    recon_id: string
    entity_kind: string
    entity_id: string
    gross: { display: string }
    fee: { display: string }
    tax: { display: string }
    settlement_effect: { display: string }
  }>
  bank_entries: Array<{
    bank_entry_id: string
    amount: { display: string }
    utr: string | null
    narration: string
  }>
  source_envelope_count: number
}



type RazorpayStatus = { configured: boolean; mode: string; api: string }
type RazorpayProbe = {
  configured: boolean
  mode: string
  account_fingerprint: string
  payments: number
  payment_statuses: Record<string, number>
  payment_methods: Record<string, number>
  settlements: number
  recon_rows: number
  endpoints: string[]
  privacy: string
}

type AiStatus = { provider: string; configured: boolean; model: string | null }
type SchemaAdapterResult = {
  provider: AiStatus
  source_columns: string[]
  sample_rows: Array<Record<string, string>>
  target_fields: string[]
  mappings: Array<{ target_field: string; source_column: string | null; transform: string; constant: string | number | null; date_format: string | null; timezone_offset_minutes: number | null }>
  validation_state: string | null
  financial_control_verified: boolean
  error_messages: string[]
  rejection_reason: string | null
  retained_raw_envelopes: number
  expected_total: { display: string }
}

type RunEvent = {
  event: string
  stage?: string
  label?: string
  processed?: number
  total?: number
  duration_seconds?: number
  latest_settlement_id?: string
  latest_status?: string
  nodes?: number
  edges?: number
  status_counts?: Record<string, number>
  run?: RunSummary
  detail?: string
}

const defaultStatus: DemoStatus = {
  phase: 'ready', dataset: null, run: null, truth_unlocked: false,
  evaluation: null, can_generate: true, can_run: false, can_unlock: false,
}

function pct(value: number | null) {
  return value == null ? '—' : `${(value * 100).toFixed(2)}%`
}

function compactHash(value: string) {
  return `${value.slice(0, 12)}…${value.slice(-8)}`
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function PitchDemoPage() {
  const [status, setStatus] = useState<DemoStatus>(defaultStatus)
  const [count, setCount] = useState(500)
  const [profile, setProfile] = useState('reconciliation_adversarial')
  const [worldSeed, setWorldSeed] = useState(402)
  const [observationSeed, setObservationSeed] = useState(1402)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [running, setRunning] = useState(false)
  const [rows, setRows] = useState<SettlementRow[]>([])
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<ProofDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [schemaResult, setSchemaResult] = useState<SchemaAdapterResult | null>(null)
  const [schemaRunning, setSchemaRunning] = useState(false)
  const [razorpayStatus, setRazorpayStatus] = useState<RazorpayStatus | null>(null)
  const [razorpayProbe, setRazorpayProbe] = useState<RazorpayProbe | null>(null)
  const [razorpayRunning, setRazorpayRunning] = useState(false)

  async function refreshStatus() {
    setStatus(await json<DemoStatus>('/api/v1/demo/status'))
  }

  useEffect(() => {
    void refreshStatus().catch(() => undefined)
    void json<AiStatus>('/api/v1/demo/ai-status').then(setAiStatus).catch(() => undefined)
    void json<RazorpayStatus>('/api/v1/demo/razorpay-status').then(setRazorpayStatus).catch(() => undefined)
  }, [])

  async function generate() {
    setError(null); setRows([]); setSelected(null); setEvents([])
    const next = await json<DemoStatus>('/api/v1/demo/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settlement_count: count, profile, world_seed: worldSeed, observation_seed: observationSeed }),
    })
    setStatus(next)
  }

  function run() {
    setError(null); setEvents([]); setRunning(true); setSelected(null)
    const source = new EventSource('/api/v1/demo/run-stream')
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as RunEvent
      setEvents((current) => [...current, event])
      if (event.event === 'run_completed' || event.event === 'source_rejected' || event.event === 'error') {
        source.close(); setRunning(false)
        if (event.event === 'error') setError(event.detail ?? 'Run failed')
        void refreshStatus().then(async () => {
          const nextRows = await json<SettlementRow[]>('/api/v1/demo/settlements')
          setRows(nextRows)
        })
      }
    }
    source.onerror = () => { source.close(); setRunning(false); setError('Run stream disconnected') }
  }

  async function unlock() {
    setError(null)
    const evaluation = await json<Evaluation>('/api/v1/demo/unlock-truth', { method: 'POST' })
    setStatus((current) => ({ ...current, phase: 'truth_unlocked', truth_unlocked: true, evaluation, can_unlock: false }))
  }

  async function reset() {
    await json('/api/v1/demo/reset', { method: 'POST' })
    setStatus(defaultStatus); setRows([]); setSelected(null); setEvents([]); setError(null)
  }

  async function openProof(settlementId: string) {
    setSelected(await json<ProofDetail>(`/api/v1/demo/settlements/${encodeURIComponent(settlementId)}`))
  }

  async function probeRazorpay() {
    setRazorpayRunning(true); setError(null)
    try {
      setRazorpayProbe(await json<RazorpayProbe>('/api/v1/demo/razorpay-probe', { method: 'POST' }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Razorpay API probe failed')
    } finally {
      setRazorpayRunning(false)
    }
  }

  async function runSchemaAdapter() {
    setSchemaRunning(true); setError(null)
    try {
      setSchemaResult(await json<SchemaAdapterResult>('/api/v1/demo/schema-adapter', { method: 'POST' }))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Schema proposal failed')
    } finally {
      setSchemaRunning(false)
    }
  }

  const current = [...events].reverse().find((event) => event.event === 'progress' || event.event === 'stage_started')
  const filtered = useMemo(() => rows.filter((row) => {
    if (filter !== 'all' && row.status !== filter) return false
    return !query || row.settlement_id.toLowerCase().includes(query.toLowerCase())
  }), [filter, query, rows])

  return <section className="pitch-page">
    <header className="pitch-header">
      <div><span className="eyebrow">Reconciliation run</span><h1>Close a Razorpay-shaped settlement batch</h1><p>Generate a reproducible workload, reconcile it, inspect the exceptions, then unlock ground truth.</p></div>
      <button className="ghost-action" onClick={() => void reset()} disabled={running}><RotateCcw size={15} /> Reset</button>
    </header>

    {error && <div className="pitch-error"><ShieldAlert size={16} />{error}</div>}

    <section className="dataset-builder">
      <div className="builder-copy"><span className="eyebrow">Workload</span><strong>Synthetic, reproducible, scored after the run</strong><small>Ground truth is never passed to the reconciliation engine.</small></div>
      <label>Settlements<select value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={running}><option value={100}>100</option><option value={250}>250</option><option value={500}>500</option><option value={1000}>1,000</option></select></label>
      <label>Profile<select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={running}><option value="clean">Normal month</option><option value="reconciliation_adversarial">Adversarial close</option><option value="source_schema_adversarial">Schema drift</option></select></label>
      <label>World seed<input type="number" value={worldSeed} onChange={(e) => setWorldSeed(Number(e.target.value))} disabled={running} /></label>
      <label>Observation seed<input type="number" value={observationSeed} onChange={(e) => setObservationSeed(Number(e.target.value))} disabled={running} /></label>
      <button className="primary-action" onClick={() => void generate()} disabled={running}><Database size={16} /> Generate batch</button>
    </section>

    <section className="razorpay-connector">
      <div className="connector-head"><div><span className="eyebrow">Razorpay API</span><strong>Live connector check</strong><small>This is separate from the scored synthetic workload.</small></div><div className={`connector-state ${razorpayStatus?.configured ? 'connector-ready' : ''}`}><span>{razorpayStatus?.mode ?? 'test'} mode</span><strong>{razorpayStatus?.configured ? 'Credentials configured' : 'Credentials not configured'}</strong></div></div>
      <div className="endpoint-row"><code>/v1/payments</code><code>/v1/settlements</code><code>/v1/settlements/recon/combined</code><button disabled={!razorpayStatus?.configured || razorpayRunning} onClick={() => void probeRazorpay()}>{razorpayRunning ? 'Checking…' : 'Check Razorpay API'}</button></div>
      {razorpayProbe && <div className="connector-results"><div><span>Payments</span><strong>{razorpayProbe.payments}</strong></div><div><span>Settlements</span><strong>{razorpayProbe.settlements}</strong></div><div><span>Recon rows</span><strong>{razorpayProbe.recon_rows}</strong></div><div><span>Account</span><code>{razorpayProbe.account_fingerprint}</code></div><p>{razorpayProbe.privacy}</p></div>}
    </section>

    {status.dataset && <>
      <section className="dataset-proofbar">
        <div><span>Observed records</span><strong>{status.dataset.observed_record_count.toLocaleString()}</strong></div>
        <div><span>Settlements</span><strong>{status.dataset.settlement_count.toLocaleString()}</strong></div>
        <div><span>Injected corruptions</span><strong>{status.dataset.corruption_count.toLocaleString()}</strong></div>
        <div className="hash-cell"><span>Dataset SHA-256</span><code title={status.dataset.dataset_sha256}>{compactHash(status.dataset.dataset_sha256)}</code></div>
        <div className="hash-cell truth-lock"><span><LockKeyhole size={12} /> Truth commitment</span><code title={status.dataset.truth_commitment_sha256}>{compactHash(status.dataset.truth_commitment_sha256)}</code></div>
      </section>

      <section className="source-ledger">
        {Object.entries(status.dataset.source_counts).map(([name, value]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><strong>{value.toLocaleString()}</strong><small>records</small></div>)}
      </section>
    </>}

    {status.can_run && !running && <button className="run-button" onClick={run}><Play size={20} fill="currentColor" /><span><strong>Run reconciliation</strong><small>Process the observed evidence. Ground truth stays locked.</small></span></button>}

    {(running || events.length > 0) && <section className="run-console">
      <div className="console-head"><div><span className="eyebrow">Engine</span><strong>{running ? 'Reconciliation in progress' : status.run?.source_rejection ? 'Source rejected' : 'Run complete'}</strong></div>{current?.processed != null && current.total != null && <b>{current.processed.toLocaleString()} / {current.total.toLocaleString()}</b>}</div>
      {current?.processed != null && current.total != null && <div className="real-progress"><span style={{ width: `${Math.min(100, current.processed / current.total * 100)}%` }} /></div>}
      <div className="stage-list">{events.filter((event) => event.event === 'stage_completed' || event.event === 'stage_started').map((event, index) => <div className="stage-line" key={`${event.stage}-${index}`}><span>{event.event === 'stage_completed' ? <CheckCircle2 size={15} /> : <Activity className="spin" size={15} />}</span><strong>{event.label ?? event.stage}</strong>{event.duration_seconds != null && <small>{event.duration_seconds.toFixed(3)} s</small>}</div>)}</div>
      {current?.latest_settlement_id && <div className="latest-proof"><span>Latest proof</span><code>{current.latest_settlement_id}</code><StatusPill status={current.latest_status ?? 'unknown'} /></div>}
    </section>}

    {status.run && !status.run.source_rejection && <>
      <section className="run-summary">
        <div><span>Total runtime</span><strong>{status.run.elapsed_seconds.toFixed(2)} s</strong></div>
        <div><span>Money Graph</span><strong>{status.run.graph_edges.toLocaleString()}</strong><small>authoritative edges</small></div>
        <div><span>Proof stages</span><strong>{status.run.proof_pipeline_seconds.toFixed(2)} s</strong><small>{status.run.settlements_per_second.toLocaleString()} settlements/s</small></div>
        <div><span>Explicit exceptions</span><strong>{status.run.exception_count.toLocaleString()}</strong></div>
      </section>

      <section className="outcome-strip">{Object.entries(status.run.status_counts).filter(([, value]) => value > 0).map(([name, value]) => <button key={name} onClick={() => setFilter(name)}><StatusPill status={name} /><strong>{value.toLocaleString()}</strong></button>)}</section>

      <div className="results-toolbar"><div><span className="eyebrow">Settlement proofs</span><strong>{filtered.length.toLocaleString()} shown</strong></div><label><Search size={14} /><input placeholder="Search settlement ID" value={query} onChange={(e) => setQuery(e.target.value)} /></label><select value={filter} onChange={(e) => setFilter(e.target.value)}><option value="all">All outcomes</option>{Object.keys(status.run.status_counts).map((name) => <option key={name} value={name}>{name.replaceAll('_', ' ')}</option>)}</select></div>
      <div className="pitch-result-table"><div className="pitch-result-head"><span>Settlement</span><span>Amount</span><span>Composition</span><span>Bank</span><span>Decision</span></div>{filtered.slice(0, 80).map((row) => <button className="pitch-result-row" key={row.settlement_id} onClick={() => void openProof(row.settlement_id)}><code>{row.settlement_id}</code><strong>{row.amount.display}</strong><span>{row.composition_components} components</span><StatusPill status={row.bank_status} /><StatusPill status={row.status} /></button>)}</div>
    </>}

    {selected && <section className="proof-inspector">
      <div className="inspector-head"><div><span className="eyebrow">Settlement proof</span><h2>{selected.settlement_id}</h2></div><div><strong>{selected.settlement_amount.display}</strong><StatusPill status={selected.status} /></div></div>
      <div className="proof-equation-large"><div><span>Recon composition</span><strong>{selected.observed_composition.display}</strong></div><b>=</b><div><span>Settlement</span><strong>{selected.settlement_amount.display}</strong></div><b>Δ</b><div><span>Residual</span><strong>{selected.composition_residual.display}</strong></div></div>
      <div className="proof-equation-large"><div><span>Bank credit</span><strong>{selected.bank_observed.display}</strong></div><b>vs</b><div><span>Expected</span><strong>{selected.settlement_amount.display}</strong></div><b>Δ</b><div><span>Residual</span><strong>{selected.bank_residual.display}</strong></div></div>
      <div className="proof-meta"><span>UTR <code>{selected.settlement_utr ?? 'missing'}</code></span><span>{selected.components.length} recon components</span><span>{selected.source_envelope_count} source envelopes cited</span></div>
      <div className="component-table"><div className="component-head"><span>Entity</span><span>Gross</span><span>Fee</span><span>Tax</span><span>Settlement effect</span></div>{selected.components.slice(0, 12).map((item) => <div className="component-row" key={item.recon_id}><span><b>{item.entity_kind}</b><code>{item.entity_id}</code></span><strong>{item.gross.display}</strong><span>{item.fee.display}</span><span>{item.tax.display}</span><strong>{item.settlement_effect.display}</strong></div>)}</div>
      {selected.reason_codes.length > 0 && <div className="reason-list">{selected.reason_codes.map((reason) => <code key={reason}>{reason}</code>)}</div>}
    </section>}

    {status.run && !status.run.source_rejection && <section className="schema-lab">
      <div className="schema-head"><div><span className="eyebrow">Schema drift</span><h2>Bank export changed</h2><p>Raw rows are retained first. The model can propose a declarative mapping; deterministic checks still decide whether it is safe enough for review.</p></div><div className={`ai-provider-state ${aiStatus?.configured ? 'ai-ready' : ''}`}><span>{aiStatus?.provider ?? 'deepseek'}</span><strong>{aiStatus?.configured ? aiStatus.model : 'API key not configured'}</strong></div></div>
      <div className="schema-columns"><div><span>Incoming columns</span><code>Txn · Credit · Date · Memo · Reference</code></div><div><span>Canonical target</span><code>bank_entry_id · amount_paise · occurred_at · narration · utr</code></div></div>
      <button className="schema-action" disabled={!aiStatus?.configured || schemaRunning} onClick={() => void runSchemaAdapter()}>{schemaRunning ? 'Asking model…' : 'Propose adapter with AI'}</button>
      {schemaResult && <div className="schema-result"><div className="schema-verdict"><div><span className="eyebrow">Model proposal</span><strong>{schemaResult.mappings.length} constrained mappings</strong></div><div><StatusPill status={schemaResult.validation_state ?? 'unknown'} /><span className={schemaResult.financial_control_verified ? 'control-ok' : 'control-bad'}>{schemaResult.financial_control_verified ? `Financial control verified: ${schemaResult.expected_total.display}` : 'Financial control not verified'}</span></div></div><div className="mapping-table">{schemaResult.mappings.map((mapping) => <div key={mapping.target_field}><code>{mapping.source_column ?? String(mapping.constant)}</code><span>→</span><strong>{mapping.target_field}</strong><small>{mapping.transform}</small></div>)}</div><p>{schemaResult.rejection_reason ?? 'Proposal passed deterministic validation.'}</p></div>}
    </section>}

    {status.can_unlock && <button className="truth-button" onClick={() => void unlock()}><Unlock size={18} /><span><strong>Unlock hidden ground truth</strong><small>Score the completed run only now.</small></span></button>}

    {status.evaluation && <section className="evaluation-reveal">
      <div className="evaluation-title"><div><span className="eyebrow">Ground-truth evaluation</span><h2>Now score the decisions</h2></div><div className="commitment-ok"><CheckCircle2 size={16} /> Truth commitment verified</div></div>
      <div className="comparison-grid"><article><span className="eyebrow">ReFlow</span><strong>{status.evaluation.reflow.auto_reconciled} automatic</strong><div className="score-grid"><div><span>Correct</span><b>{status.evaluation.reflow.true_auto_reconciled}</b></div><div><span>Wrong</span><b>{status.evaluation.reflow.false_auto_reconciled}</b></div><div><span>Precision</span><b>{pct(status.evaluation.reflow.precision)}</b></div><div><span>Recall</span><b>{pct(status.evaluation.reflow.recall)}</b></div></div></article><article><span className="eyebrow">Fuzzy matcher</span><strong>{status.evaluation.fuzzy.auto_reconciled} automatic</strong><div className="score-grid"><div><span>Correct</span><b>{status.evaluation.fuzzy.true_auto_reconciled}</b></div><div><span>Wrong</span><b className="wrong-score">{status.evaluation.fuzzy.false_auto_reconciled}</b></div><div><span>Precision</span><b>{pct(status.evaluation.fuzzy.precision)}</b></div><div><span>False-match rate</span><b>{pct(status.evaluation.fuzzy.silent_false_match_rate)}</b></div></div></article></div>
    </section>}
  </section>
}
