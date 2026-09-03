import { DatabaseZap } from 'lucide-react'
import { scopedPath, usePagedApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { PaginationFooter } from '../components/PaginationFooter'
import { DataState } from '../components/StateView'
import { StatusPill } from '../components/StatusPill'
import { useScope } from '../scope'
import type { SourceLabItem } from '../types'

export function SourcesPage() {
  const { scopeId } = useScope()
  const { state, loadMore } = usePagedApi<SourceLabItem>(scopedPath(scopeId, '/sources/page'))
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">Source Lab</span><h1>Evidence delivery before interpretation.</h1></div><p>Manifest, schema and adapter metadata only. Raw source payloads stay out of this surface.</p></div><DataState state={state} empty={(data) => data.length === 0}>{(sources) => <><div className="source-strip">{sources.map((source) => <div className="source-node" key={source.manifest_id}><div className="source-node-top"><span>{source.source_kind.replaceAll('_', ' ')}</span><StatusPill status={source.completeness} /></div><strong>{source.effective_envelope_count} effective</strong><small>{source.received_late ? 'Late delivery' : source.received_at ? 'Received' : 'Not received'}</small></div>)}</div><div className="dense-table source-table"><div className="table-head"><span>Source</span><span>State</span><span>Adapter / schema</span><span>Evidence</span><span>Manifest</span></div>{sources.map((source) => <div className="table-row" key={source.manifest_id}><span className="source-name"><DatabaseZap size={16} />{source.source_kind.replaceAll('_', ' ')}</span><span><StatusPill status={source.completeness} />{source.received_late && <small>late</small>}</span><span><strong>{source.adapter_version}</strong><small>{source.schema_fingerprint}</small></span><span><strong>{source.effective_envelope_count}</strong><small>{source.delivered_envelope_count} in this delivery</small></span><ArtifactId value={source.manifest_id} /></div>)}</div></>}</DataState>{state.status === 'success' && <PaginationFooter hasMore={state.nextCursor !== null} loading={state.loadingMore} error={state.loadMoreError} onLoadMore={loadMore} />}</section>
}
