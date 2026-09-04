import {
  ArrowRight,
  Check,
  Database,
  FileCheck2,
  GitBranch,
  Landmark,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { JudgeDemoActionResult, JudgeDemoOutcome, JudgeDemoStatus } from '../types'

const actionCopy = {
  '/api/v1/demo/run': 'Run reconciliation',
  '/api/v1/demo/bank-arrival': 'Simulate bank evidence arriving',
  '/api/v1/demo/rerun': 'Re-evaluate affected proof',
} as const

function statusClass(status: string): string {
  if (status === 'proven_reconciled') return 'demo-outcome-positive'
  if (status === 'contradicted') return 'demo-outcome-danger'
  return 'demo-outcome-warning'
}

function statusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

function OutcomeCard({ outcome }: { outcome: JudgeDemoOutcome }) {
  return <article className={`demo-outcome ${statusClass(outcome.status)}`}>
    <div className="demo-outcome-top">
      <div><span>{outcome.label}</span><strong>{outcome.amount_display}</strong></div>
      <span className="demo-version">v{outcome.version}</span>
    </div>
    <div className="demo-outcome-status">{statusLabel(outcome.status)}</div>
    <div className="demo-outcome-meta">
      <span>{statusLabel(outcome.composition_status)}</span>
      <span>{statusLabel(outcome.bank_status)}</span>
      {outcome.residual_paise > 0
        ? <span>residual {outcome.residual_display}</span>
        : <span>zero residual</span>}
    </div>
  </article>
}

async function getStatus(): Promise<JudgeDemoStatus | null> {
  const response = await fetch('/api/v1/demo/status', {
    headers: { Accept: 'application/json' },
  })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`Demo status failed with HTTP ${response.status}`)
  return response.json() as Promise<JudgeDemoStatus>
}

async function postAction(path: keyof typeof actionCopy): Promise<JudgeDemoActionResult> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  const body = await response.json().catch(() => null) as { detail?: string } | null
  if (!response.ok) {
    throw new Error(body?.detail ?? `Demo action failed with HTTP ${response.status}`)
  }
  return body as JudgeDemoActionResult
}

export function JudgeDemoPanel({ onChanged }: { onChanged?: () => void }) {
  const [status, setStatus] = useState<JudgeDemoStatus | null>(null)
  const [supported, setSupported] = useState<boolean | null>(null)
  const [working, setWorking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<JudgeDemoActionResult | null>(null)
  const [visibleStages, setVisibleStages] = useState(0)

  async function refreshStatus() {
    const next = await getStatus()
    setStatus(next)
    setSupported(next !== null)
  }

  useEffect(() => {
    void refreshStatus().catch(() => setSupported(false))
  }, [])

  useEffect(() => {
    if (!result) return
    setVisibleStages(0)
    const timers = result.stages.map((_, index) => window.setTimeout(
      () => setVisibleStages(index + 1),
      420 * (index + 1),
    ))
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [result])

  async function run(path: keyof typeof actionCopy) {
    setWorking(path)
    setError(null)
    setResult(null)
    try {
      const next = await postAction(path)
      setResult(next)
      await refreshStatus()
      onChanged?.()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Demo action failed')
    } finally {
      setWorking(null)
    }
  }

  const outcomes = result?.outcomes ?? status?.outcomes ?? []
  const playbackDone = result !== null && visibleStages >= result.stages.length
  const pending = useMemo(
    () => outcomes.find((item) => item.settlement_id === 'setl_demo_pending') ?? null,
    [outcomes],
  )

  if (supported !== true || !status) return null

  return <section className="judge-demo">
    <div className="judge-demo-head">
      <div>
        <span className="eyebrow">Live judge demo · synthetic data</span>
        <h2>Watch ReFlow build the financial proof</h2>
        <p>The buttons below execute the real ingestion, Money Graph, proof and case engines. Stage playback is slowed only so the measured steps are readable on video.</p>
      </div>
      <div className="demo-authority"><ShieldCheck size={16} /><span>AI has no financial authority</span></div>
    </div>

    {status.phase === 'ready' ? <>
      <div className="demo-source-grid">
        <div><Database size={17} /><span>Merchant</span><strong>4</strong><small>orders</small></div>
        <div><GitBranch size={17} /><span>Razorpay</span><strong>4</strong><small>payment events</small></div>
        <div><FileCheck2 size={17} /><span>Settlement Recon</span><strong>4</strong><small>composition rows</small></div>
        <div><Landmark size={17} /><span>Bank</span><strong>4</strong><small>rows · one expected credit missing</small></div>
      </div>
      <div className="demo-launch-row">
        <div><strong>{status.raw_record_count} raw records · {status.settlement_count} settlements</strong><span>Nothing is reconciled yet.</span></div>
        <button className="demo-primary" disabled={working !== null} onClick={() => void run('/api/v1/demo/run')}><Play size={16} />{working ? 'Running…' : 'Run reconciliation'}</button>
      </div>
    </> : null}

    {result ? <div className="demo-run-playback">
      <div className="demo-playback-title"><span>Engine trace</span><small>measured backend time · visual playback slowed for readability</small></div>
      <div className="demo-stage-list">
        {result.stages.map((stage, index) => <div className={index < visibleStages ? 'demo-stage demo-stage-visible' : 'demo-stage'} key={stage.key}>
          <div className="demo-stage-index">{index < visibleStages ? <Check size={14} /> : index + 1}</div>
          <div><strong>{stage.label}</strong><span>{stage.facts.join(' · ')}</span></div>
          <code>{stage.duration_ms.toFixed(3)} ms</code>
        </div>)}
      </div>
      {playbackDone ? <div className="demo-result-message"><Check size={16} /><span>{result.message}</span></div> : null}
    </div> : null}

    {outcomes.length > 0 && (result === null || playbackDone) ? <div className="demo-outcome-grid">
      {outcomes.map((outcome) => <OutcomeCard key={outcome.settlement_id} outcome={outcome} />)}
    </div> : null}

    {status.phase === 'initial_run' && (result === null || playbackDone) ? <div className="demo-next-step">
      <div><span className="eyebrow">Now inspect the exception</span><strong>The ₹20,000 settlement is processed, but bank receipt is not proven.</strong><small>Open the case, show the bounded AI recommendation, then return here.</small></div>
      <div className="demo-actions">
        {status.focus_case_id ? <Link className="demo-secondary" to={`/cases/${status.focus_case_id}?scope=${encodeURIComponent(status.scope_id)}`}>Open pending case <ArrowRight size={15} /></Link> : null}
        <button className="demo-primary" disabled={working !== null} onClick={() => void run('/api/v1/demo/bank-arrival')}><Landmark size={15} />{working ? 'Receiving…' : 'Simulate bank evidence arriving'}</button>
      </div>
    </div> : null}

    {status.phase === 'bank_arrived' && (result === null || playbackDone) ? <div className="demo-next-step demo-bank-arrived">
      <div><span className="eyebrow">New authoritative evidence</span><strong>UTR-DEMO-PENDING · ₹20,000.00</strong><small>The bank row now exists, but ReFlow has not changed financial truth yet.</small></div>
      <button className="demo-primary" disabled={working !== null} onClick={() => void run('/api/v1/demo/rerun')}><RefreshCw size={15} />{working ? 'Re-evaluating…' : 'Re-evaluate affected proof'}</button>
    </div> : null}

    {status.phase === 'reconciled' && pending && (result === null || playbackDone) ? <div className="demo-next-step demo-complete">
      <div><span className="eyebrow">Proof lifecycle complete</span><strong>Pending → proven, without rewriting history.</strong><small>The focused case is auto-closed because proof v2 now contains authoritative bank evidence.</small></div>
      <div className="demo-actions">
        {status.focus_proof_id ? <Link className="demo-secondary" to={`/proofs/${status.focus_proof_id}?scope=${encodeURIComponent(status.scope_id)}`}>Open proof v2 <ArrowRight size={15} /></Link> : null}
        {status.focus_case_id ? <Link className="demo-secondary" to={`/cases/${status.focus_case_id}?scope=${encodeURIComponent(status.scope_id)}`}>Open closed case <ArrowRight size={15} /></Link> : null}
      </div>
    </div> : null}

    {error ? <div className="demo-error">{error}</div> : null}
  </section>
}
