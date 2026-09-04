import { AlertOctagon, ArrowRight, CheckCircle2, Database, Scale } from 'lucide-react'
import { Link } from 'react-router-dom'
import { scopedPath, useApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { DataState } from '../components/StateView'
import { StatusPill } from '../components/StatusPill'
import { useScope } from '../scope'
import type { Overview } from '../types'

export function OverviewPage() {
  const { scopeId } = useScope()
  const state = useApi<Overview>(scopedPath(scopeId, '/overview'))
  return <section className="page-stack">
    <div className="page-heading"><div><span className="eyebrow">Run / Close Overview</span><h1>Can finance close this scope?</h1></div><p>Every number below is a projection of immutable proof/control artifacts.</p></div>
    <DataState state={state}>{(data) => data.has_current_run && data.run ? <>
      <div className={`close-hero close-${data.run.close_status === 'ready' ? 'ready' : 'blocked'}`}>
        <div className="close-icon">{data.run.close_status === 'ready' ? <CheckCircle2 size={30} /> : <AlertOctagon size={30} />}</div>
        <div className="close-copy"><span className="eyebrow">Close readiness</span><div className="close-title"><h2>{data.run.close_status === 'ready' ? 'Ready to close' : 'Close blocked'}</h2><StatusPill status={data.run.close_status} /></div><p>{data.run.close_reason_codes.length ? data.run.close_reason_codes.join(' · ') : 'No blocking control reasons.'}</p></div>
        <div className="run-meta"><span>Current run</span><ArtifactId value={data.run.run_id} /><small>{new Date(data.run.completed_at).toLocaleString()}</small></div>
      </div>

      <div className="metric-rail">
        {data.proof_status.map((item) => <div className="metric-cell" key={item.status}><StatusPill status={item.status} /><strong>{item.amount.display}</strong><span>{item.count} settlement{item.count === 1 ? '' : 's'}</span></div>)}
      </div>

      <div className="overview-grid">
        <article className="evidence-panel"><div className="panel-kicker"><Scale size={17} />Balance control</div><div className="panel-value-row"><strong>{data.run.balance_residual.display}</strong><StatusPill status={data.run.balance_status} /></div><p>Exact residual; no tolerance is applied.</p><ArtifactId value={data.run.balance_control_id} /></article>
        <article className="evidence-panel"><div className="panel-kicker"><Database size={17} />No-orphan coverage</div><div className="panel-value-row"><strong>{data.run.orphan_count} orphan records</strong><StatusPill status={data.run.coverage_status} /></div><p>Known orphan value: {data.run.orphan_known_value.display}</p><ArtifactId value={data.run.coverage_certificate_id} /></article>
        <article className="evidence-panel"><div className="panel-kicker"><AlertOctagon size={17} />Active exceptions</div><div className="panel-value-row"><strong>{data.active_exception_count}</strong><span>{data.active_exception_value?.display ?? '—'}</span></div><p>Workflow priority does not change proof truth.</p><Link className="inline-link" to={`/exceptions?scope=${encodeURIComponent(scopeId)}`}>Open queue <ArrowRight size={15} /></Link></article>
      </div>

      <section className="source-strip-section"><div className="section-heading"><div><span className="eyebrow">Source health</span><h2>What evidence arrived?</h2></div><Link className="inline-link" to={`/sources?scope=${encodeURIComponent(scopeId)}`}>Source Lab <ArrowRight size={15} /></Link></div><div className="source-strip">{data.sources.map((source) => <div className="source-node" key={source.manifest_id}><div className="source-node-top"><span>{source.source_kind.replaceAll('_', ' ')}</span><StatusPill status={source.completeness} /></div><strong>{source.effective_envelope_count} effective envelopes</strong><small>{source.received_late ? 'Received late' : source.received_at ? 'Delivery observed' : 'Awaiting delivery'}</small></div>)}</div></section>
    </> : <div className="state-panel"><Database size={20} /><div><strong>No current reconciliation run</strong><span>ReFlow is not inferring a READY state from absence.</span></div></div>}</DataState>
  </section>
}
