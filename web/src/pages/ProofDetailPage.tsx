import { ArrowLeft, Landmark, Network, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { scopedPath, useApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { DataState } from '../components/StateView'
import { StatusPill } from '../components/StatusPill'
import { useScope } from '../scope'
import type { ProofDetail } from '../types'

function Equation({ left, residual, right, label }: { left: string; residual: string; right: string; label: string }) {
  return <div className="equation-block"><span className="equation-label">{label}</span><div className="equation"><strong>{left}</strong><span>+</span><strong className="residual-value">{residual}</strong><span>=</span><strong>{right}</strong></div></div>
}

export function ProofDetailPage() {
  const { scopeId } = useScope()
  const { proofId = '' } = useParams()
  const state = useApi<ProofDetail>(scopedPath(scopeId, `/proofs/${encodeURIComponent(proofId)}`))
  return <section className="page-stack"><Link className="back-link" to={`/proofs?scope=${encodeURIComponent(scopeId)}`}><ArrowLeft size={15} />All proofs</Link><DataState state={state}>{(proof) => <>
    <div className="proof-header"><div><span className="eyebrow">Settlement proof · v{proof.version}</span><h1>{proof.composition.settlement_amount.display}</h1><div className="id-line"><ArtifactId value={proof.settlement_id} /><ArtifactId value={proof.proof_id} /></div></div><StatusPill status={proof.status} /></div>
    <div className="proof-equations">
      <article className="proof-fragment"><div className="fragment-title"><Network size={18} /><div><strong>Settlement composition</strong><span>Gate 7 · provider economics</span></div><StatusPill status={proof.composition.status} /></div><Equation label="Observed components + residual = authoritative settlement" left={proof.composition.observed_composition.display} residual={proof.composition.residual.display} right={proof.composition.settlement_amount.display} /><div className="reason-list">{proof.composition.reason_codes.length ? proof.composition.reason_codes.map((reason) => <code key={reason}>{reason}</code>) : <span className="quiet"><ShieldCheck size={14} />Exact composition holds.</span>}</div></article>
      <article className="proof-fragment"><div className="fragment-title"><Landmark size={18} /><div><strong>Bank receipt</strong><span>Gate 8 · independent cash evidence</span></div><StatusPill status={proof.bank.status} /></div><Equation label="Observed bank credit + residual = expected payout" left={proof.bank.observed_bank_credit.display} residual={proof.bank.residual.display} right={proof.bank.expected_amount.display} /><div className="reason-list">{proof.bank.reason_codes.length ? proof.bank.reason_codes.map((reason) => <code key={reason}>{reason}</code>) : <span className="quiet"><ShieldCheck size={14} />Independent bank proof holds.</span>}</div></article>
    </div>
    <div className="proof-lower-grid"><article className="evidence-panel"><div className="panel-kicker">Combined reasons</div>{proof.reason_codes.length ? <div className="reason-list">{proof.reason_codes.map((reason) => <code key={reason}>{reason}</code>)}</div> : <p>No combined failure reasons.</p>}<small>Knowledge cutoff: {new Date(proof.knowledge_cutoff).toLocaleString()}</small></article><article className="evidence-panel"><div className="panel-kicker">Raw provenance</div><div className="id-stack">{proof.source_envelope_ids.map((id) => <ArtifactId key={id} value={id} />)}</div></article></div>
    <section><div className="section-heading"><div><span className="eyebrow">Version timeline</span><h2>Proof history</h2></div></div><div className="timeline">{proof.version_timeline.map((item) => <div className="timeline-item" key={item.proof_id}><span className="timeline-dot" /><div><div className="timeline-title"><strong>Version {item.version}</strong><StatusPill status={item.status} /></div><ArtifactId value={item.proof_id} /><small>{new Date(item.generated_at).toLocaleString()}{item.reopened ? ' · reopened' : ''}</small></div></div>)}</div></section>
  </>}</DataState></section>
}
