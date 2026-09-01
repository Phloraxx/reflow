const positive = new Set(['ready', 'proven', 'proven_reconciled', 'complete', 'validated', 'bank_receipt_proven', 'composition_proven'])
const danger = new Set(['not_ready', 'residual', 'contradicted', 'failed', 'bank_receipt_contradicted', 'composition_contradicted', 'provider_error', 'rejected'])
const warning = new Set(['pending_bank_credit', 'waiting', 'late', 'partial', 'incomplete', 'acknowledged', 'awaiting_source', 'deferred', 'bank_receipt_waiting', 'bank_receipt_incomplete'])

export function StatusPill({ status }: { status: string }) {
  const tone = positive.has(status) ? 'positive' : danger.has(status) ? 'danger' : warning.has(status) ? 'warning' : 'neutral'
  return <span className={`status-pill status-${tone}`}>{status.replaceAll('_', ' ')}</span>
}
