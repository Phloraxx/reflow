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

function percent(value: unknown): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—'
}

type Artifact = EvaluationLab['artifacts'][number]

function FinalSummaryCard({ artifact }: { artifact: Artifact }) {
  return <article className="evaluation-card evaluation-final">
    <div className="eval-head"><div><span className="eyebrow">Final held-out campaign</span><strong>{artifact.filename}</strong></div><ShieldCheck size={20} /></div>
    <div className="eval-metrics">
      <div><Gauge size={15} /><span>Safe coverage</span><strong>{percent(artifact.metrics.safe_match_rate)}</strong></div>
      <div><ShieldCheck size={15} /><span>Auto precision</span><strong>{percent(artifact.metrics.auto_match_precision)}</strong></div>
      <div><span>↗</span><span>Truth recall</span><strong>{percent(artifact.metrics.truth_reconciled_recall)}</strong></div>
      <div><span>0</span><span>False auto matches</span><strong>{display(artifact.metrics.false_auto_reconciled)}</strong></div>
    </div>
    <div className="eval-proofline">
      <span><b>{display(artifact.config.settlement_count)}</b> held-out settlements</span>
      <span><b>{display(artifact.metrics.non_green_decisions)}</b> explicit exceptions</span>
      <span><b>{display(artifact.metrics.fuzzy_false_auto_reconciled)}</b> fuzzy baseline false matches</span>
      <span><b>{display(artifact.metrics.source_schema_fail_closed_cases)}/{display(artifact.metrics.source_schema_case_count)}</b> schema fail-closed</span>
      <span><b>{display(artifact.metrics.failure_campaign_passed)}/{display(artifact.metrics.failure_campaign_check_count)}</b> regression checks</span>
    </div>
    {artifact.status_counts && <StatusCounts values={artifact.status_counts} />}
    <ArtifactFooter artifact={artifact} />
  </article>
}

function BenchmarkCard({ artifact }: { artifact: Artifact }) {
  const isScale = artifact.schema_version === 'gate17-scale-benchmark-v1'
  const isPersistence = artifact.schema_version === 'gate17-persistence-benchmark-v1'
  return <article className="evaluation-card">
    <div className="eval-head"><div><span className="eyebrow">{artifact.schema_version}</span><strong>{artifact.filename}</strong></div><ShieldCheck size={20} /></div>
    <div className="eval-metrics">
      {isScale && <>
        <div><Gauge size={15} /><span>Workload</span><strong>{display(artifact.config.settlement_count)} settlements</strong></div>
        <div><Cpu size={15} /><span>Proof pipeline</span><strong>{display(artifact.metrics.settlements_per_second_proof_pipeline)} /s</strong></div>
        <div><HardDrive size={15} /><span>Peak RSS</span><strong>{display(artifact.metrics.max_rss_kib)} KiB</strong></div>
        <div><span>Σ</span><span>Raw rows</span><strong>{display(artifact.metrics.raw_rows)}</strong></div>
      </>}
      {isPersistence && <>
        <div><Gauge size={15} /><span>Records</span><strong>{display(artifact.config.record_count)}</strong></div>
        <div><span>↓</span><span>Cold source writes</span><strong>{display(artifact.metrics.source_cold_ops_per_second)} /s</strong></div>
        <div><span>↻</span><span>Warm source replay</span><strong>{display(artifact.metrics.source_warm_ops_per_second)} /s</strong></div>
        <div><span>□</span><span>Cold artifact writes</span><strong>{display(artifact.metrics.artifact_cold_ops_per_second)} /s</strong></div>
      </>}
    </div>
    {artifact.status_counts && <StatusCounts values={artifact.status_counts} />}
    <ArtifactFooter artifact={artifact} />
  </article>
}

function StatusCounts({ values }: { values: Record<string, unknown> }) {
  return <div className="status-counts">{Object.entries(values).map(([key, value]) => <span key={key}><b>{display(value)}</b>{key.replaceAll('_', ' ')}</span>)}</div>
}

function ArtifactFooter({ artifact }: { artifact: Artifact }) {
  return <div className="eval-foot"><ArtifactId value={artifact.artifact_sha256} /><span>{display(artifact.hardware.machine)} · Python {display(artifact.hardware.python)}</span></div>
}

export function EvaluationPage() {
  const state = useApi<EvaluationLab>('/api/v1/evaluation')
  return <section className="page-stack">
    <div className="page-heading"><div><span className="eyebrow">Evaluation Lab</span><h1>Claims backed by checked-in artifacts.</h1></div><p>No extrapolated 100k/1M result. Every displayed artifact passed its stored digest verifier.</p></div>
    <DataState state={state} empty={(data) => data.artifacts.length === 0}>{(data) => <div className="evaluation-grid">{data.artifacts.map((artifact) => artifact.schema_version === 'gate19-final-summary-v1' ? <FinalSummaryCard artifact={artifact} key={artifact.filename} /> : <BenchmarkCard artifact={artifact} key={artifact.filename} />)}</div>}</DataState>
  </section>
}
