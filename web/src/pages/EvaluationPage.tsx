import { Cpu, Gauge, HardDrive, ShieldCheck } from 'lucide-react'
import { useApi } from '../api'
import { ArtifactId } from '../components/ArtifactId'
import { DataState } from '../components/StateView'
import type { EvaluationLab } from '../types'

function display(value: unknown): string {
  if (typeof value === 'number') return value.toLocaleString()
  if (typeof value === 'string') return value
  if (value == null) return '—'
  return JSON.stringify(value)
}

export function EvaluationPage() {
  const state = useApi<EvaluationLab>('/api/v1/evaluation')
  return <section className="page-stack"><div className="page-heading"><div><span className="eyebrow">Evaluation Lab</span><h1>Claims backed by checked-in artifacts.</h1></div><p>No extrapolated 100k/1M result. Every displayed artifact passed its stored digest verifier.</p></div><DataState state={state} empty={(data) => data.artifacts.length === 0}>{(data) => <div className="evaluation-grid">{data.artifacts.map((artifact) => <article className="evaluation-card" key={artifact.filename}><div className="eval-head"><div><span className="eyebrow">{artifact.schema_version}</span><strong>{artifact.filename}</strong></div><ShieldCheck size={20} /></div><div className="eval-metrics">{'settlement_count' in artifact.config && <><div><Gauge size={15} /><span>Workload</span><strong>{display(artifact.config.settlement_count)} settlements</strong></div><div><Cpu size={15} /><span>Proof pipeline</span><strong>{display(artifact.metrics.settlements_per_second_proof_pipeline)} /s</strong></div><div><HardDrive size={15} /><span>Peak RSS</span><strong>{display(artifact.metrics.max_rss_kib)} KiB</strong></div><div><span>Σ</span><span>Raw rows</span><strong>{display(artifact.metrics.raw_rows)}</strong></div></>}{'record_count' in artifact.config && <><div><Gauge size={15} /><span>Records</span><strong>{display(artifact.config.record_count)}</strong></div><div><span>↓</span><span>Cold source writes</span><strong>{display(artifact.metrics.source_cold_ops_per_second)} /s</strong></div><div><span>↻</span><span>Warm source replay</span><strong>{display(artifact.metrics.source_warm_ops_per_second)} /s</strong></div><div><span>□</span><span>Cold artifact writes</span><strong>{display(artifact.metrics.artifact_cold_ops_per_second)} /s</strong></div></>}</div>{artifact.status_counts && <div className="status-counts">{Object.entries(artifact.status_counts).map(([key, value]) => <span key={key}><b>{display(value)}</b>{key.replaceAll('_', ' ')}</span>)}</div>}<div className="eval-foot"><ArtifactId value={artifact.artifact_sha256} /><span>{display(artifact.hardware.machine)} · Python {display(artifact.hardware.python)}</span></div></article>)}</div>}</DataState></section>
}
