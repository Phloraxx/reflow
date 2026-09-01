import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { scopedPath, useApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { DataState } from '../components/StateView'
import { StatusPill } from '../components/StatusPill'
import { useScope } from '../scope'
import type { ProofListItem } from '../types'

export function ProofsPage() {
  const { scopeId } = useScope()
  const state = useApi<ProofListItem[]>(scopedPath(scopeId, '/proofs'))
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">Settlement Proofs</span><h1>Every settlement gets a proof state.</h1></div><p>Versioned Gate 7 + Gate 8 evidence combined by Gate 9.</p></div><DataState state={state} empty={(data) => data.length === 0}>{(proofs) => <div className="dense-table"><div className="table-head"><span>Status</span><span>Settlement</span><span>Amount</span><span>Version</span><span>Generated</span><span /></div>{proofs.map((proof) => <Link className="table-row proof-row" to={`/proofs/${encodeURIComponent(proof.proof_id)}?scope=${encodeURIComponent(scopeId)}`} key={proof.proof_id}><span><StatusPill status={proof.status} /></span><span><ArtifactId value={proof.settlement_id} /></span><strong>{proof.settlement_amount.display}</strong><span>v{proof.version}{proof.reopened ? ' · reopened' : ''}</span><span>{new Date(proof.generated_at).toLocaleString()}</span><ChevronRight size={16} /></Link>)}</div>}</DataState></section>
}
