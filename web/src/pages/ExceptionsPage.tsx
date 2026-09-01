import { ChevronRight, Filter } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { scopedPath, useApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { DataState } from '../components/StateView'
import { StatusPill } from '../components/StatusPill'
import { useScope } from '../scope'
import type { ExceptionItem } from '../types'

function age(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

export function ExceptionsPage() {
  const { scopeId } = useScope()
  const state = useApi<ExceptionItem[]>(scopedPath(scopeId, '/exceptions'))
  const [status, setStatus] = useState('all')
  const [materiality, setMateriality] = useState('all')
  const [blocker, setBlocker] = useState('')
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">Exception Queue</span><h1>Unproven money stays explicit.</h1></div><p>Priority is workflow metadata; proof status remains untouched.</p></div><DataState state={state} empty={(data) => data.length === 0}>{(items) => <ExceptionBody items={items} scopeId={scopeId} status={status} materiality={materiality} blocker={blocker} setStatus={setStatus} setMateriality={setMateriality} setBlocker={setBlocker} />}</DataState></section>
}

function ExceptionBody({ items, scopeId, status, materiality, blocker, setStatus, setMateriality, setBlocker }: { items: ExceptionItem[]; scopeId: string; status: string; materiality: string; blocker: string; setStatus: (value: string) => void; setMateriality: (value: string) => void; setBlocker: (value: string) => void }) {
  const filtered = useMemo(() => items.filter((item) => (status === 'all' || item.financial_status === status) && (materiality === 'all' || item.materiality_band === materiality) && (!blocker || item.source_blockers.some((value) => value.toLowerCase().includes(blocker.toLowerCase())))), [items, status, materiality, blocker])
  return <><div className="filter-bar"><Filter size={16} /><select aria-label="Financial status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All financial states</option>{[...new Set(items.map((item) => item.financial_status))].map((value) => <option value={value} key={value}>{value.replaceAll('_', ' ')}</option>)}</select><select aria-label="Materiality" value={materiality} onChange={(event) => setMateriality(event.target.value)}><option value="all">All materiality</option>{['critical', 'high', 'medium', 'low'].map((value) => <option value={value} key={value}>{value}</option>)}</select><input aria-label="Source blocker" placeholder="Filter source blocker" value={blocker} onChange={(event) => setBlocker(event.target.value)} /><span>{filtered.length} / {items.length}</span></div><div className="exception-list">{filtered.map((item) => <Link to={`/cases/${encodeURIComponent(item.case_id)}?scope=${encodeURIComponent(scopeId)}`} className={`exception-row ${item.is_active ? '' : 'exception-inactive'}`} key={item.case_id}><div className={`materiality-stripe materiality-${item.materiality_band}`} /><div className="exception-primary"><div><StatusPill status={item.financial_status} /><span className="materiality-label">{item.materiality_band}</span></div><strong>{item.affected_amount.display}</strong><ArtifactId value={item.settlement_id} /></div><div className="exception-workflow"><span>Workflow</span><strong>{item.workflow_status.replaceAll('_', ' ')}</strong><small>{item.owner ?? 'Unassigned'}</small></div><div className="exception-blocker"><span>Source blocker</span><strong>{item.source_blockers.join(' · ') || 'No source blocker'}</strong><ArtifactId value={item.incident_fingerprint_id} /></div><div className="exception-age"><span>Age</span><strong>{age(item.age_seconds)}</strong><small>{item.observation_count} observations</small></div><ChevronRight size={18} /></Link>)}</div></>
}
