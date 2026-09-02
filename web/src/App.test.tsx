import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

const money = (amount_paise: number, display: string) => ({ amount_paise, currency: 'INR', display })

const overview = {
  scope_id: 'scope_ui', has_current_run: true,
  run: { run_id: 'run_ui', outcome: 'not_ready', period_start: '2026-08-31T17:30:00+00:00', period_end: '2026-09-01T17:30:00+00:00', reporting_timezone: 'Asia/Kolkata', knowledge_cutoff: '2026-09-01T17:20:00+00:00', completed_at: '2026-09-01T17:30:00+00:00', code_build_sha: 'abc', close_readiness_id: 'close_ui', close_status: 'not_ready', close_reason_codes: ['BALANCE_CONTROL_RESIDUAL'], coverage_certificate_id: 'coverage_ui', coverage_status: 'complete', orphan_count: 0, orphan_known_value: money(0, '₹0.00'), balance_control_id: 'balance_ui', balance_status: 'residual', balance_residual: money(500, '₹5.00') },
  proof_status: [{ status: 'proven_reconciled', count: 1, amount: money(10000, '₹100.00') }, { status: 'residual', count: 1, amount: money(20000, '₹200.00') }],
  sources: [{ manifest_id: 'manifest_bank', source_kind: 'bank', completeness: 'late', received_late: true, delivery_mode: 'snapshot', expected_by: '2026-09-01T15:30:00+00:00', received_at: null, watermark_at: null, adapter_version: 'v1', schema_fingerprint: 'bank-v1', delivered_envelope_count: 1, effective_envelope_count: 1 }],
  active_exception_count: 1, active_exception_value: money(20000, '₹200.00'),
}

const proof = {
  proof_id: 'proofv_break', settlement_id: 'setl_break', version: 1, status: 'residual', reason_codes: ['SETTLEMENT_COMPOSITION_RESIDUAL'], reopened: false, prior_version_id: null, knowledge_cutoff: '2026-09-01T17:00:00+00:00', generated_at: '2026-09-01T17:01:00+00:00', source_envelope_ids: ['src_1'],
  composition: { status: 'composition_residual', settlement_amount: money(20000, '₹200.00'), observed_composition: money(19500, '₹195.00'), residual: money(500, '₹5.00'), component_ids: ['recon_1'], source_envelope_ids: ['src_1'], reason_codes: ['SETTLEMENT_COMPOSITION_RESIDUAL'] },
  bank: { status: 'bank_receipt_proven', settlement_utr: 'UTR1', expected_amount: money(20000, '₹200.00'), observed_bank_credit: money(20000, '₹200.00'), residual: money(0, '₹0.00'), bank_entry_ids: ['bank_1'], source_envelope_ids: ['src_2'], reason_codes: [] },
  version_timeline: [{ proof_id: 'proofv_break', settlement_id: 'setl_break', version: 1, status: 'residual', settlement_amount: money(20000, '₹200.00'), reason_codes: ['SETTLEMENT_COMPOSITION_RESIDUAL'], knowledge_cutoff: '2026-09-01T17:00:00+00:00', generated_at: '2026-09-01T17:01:00+00:00', reopened: false }],
}

const exceptions = [
  { case_id: 'case_high', settlement_id: 'setl_break', latest_observation_id: 'obs_1', latest_proof_version_id: 'proofv_break', financial_status: 'residual', materiality_band: 'high', affected_amount: money(20000, '₹200.00'), workflow_status: 'awaiting_source', resolution: null, owner: 'finance-ops', incident_fingerprint_id: 'incident_1', incident_cluster_id: 'cluster_1', source_blockers: ['bank:late:late'], first_seen_at: '2026-09-01T13:30:00+00:00', last_seen_at: '2026-09-01T16:30:00+00:00', age_seconds: 14400, observation_count: 2, disposition_count: 2, superseded_by_case_id: null, is_active: true },
  { case_id: 'case_critical', settlement_id: 'setl_critical', latest_observation_id: 'obs_2', latest_proof_version_id: 'proofv_critical', financial_status: 'contradicted', materiality_band: 'critical', affected_amount: money(90000, '₹900.00'), workflow_status: 'open', resolution: null, owner: null, incident_fingerprint_id: 'incident_2', incident_cluster_id: null, source_blockers: [], first_seen_at: '2026-09-01T15:30:00+00:00', last_seen_at: '2026-09-01T15:30:00+00:00', age_seconds: 7200, observation_count: 1, disposition_count: 0, superseded_by_case_id: null, is_active: true },
]

function mockFetch(routes: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const path = String(input)
    const hit = Object.entries(routes).find(([key]) => path.includes(key))
    if (!hit) return Promise.resolve(new Response(JSON.stringify({ detail: 'not mocked' }), { status: 404, headers: { 'Content-Type': 'application/json' } }))
    return Promise.resolve(new Response(JSON.stringify(hit[1]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  }))
}

function renderAt(path: string) {
  window.history.replaceState({}, '', '/?scope=scope_ui')
  return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ReFlow control tower', () => {
  it('renders the close overview with persistent scope and read-only authority', async () => {
    mockFetch({ '/overview': overview })
    renderAt('/?scope=scope_ui')
    expect(await screen.findByText('Close blocked')).toBeInTheDocument()
    expect(screen.getByDisplayValue('scope_ui')).toBeInTheDocument()
    expect(screen.getByText('READ ONLY')).toBeInTheDocument()
    expect(screen.getByText('₹100.00')).toBeInTheDocument()
    expect(screen.getByText('bank')).toBeInTheDocument()
    expect(screen.queryByText(/chat/i)).not.toBeInTheDocument()
  })

  it('renders proof equations using API-supplied values', async () => {
    mockFetch({ '/proofs/proofv_break': proof })
    renderAt('/proofs/proofv_break?scope=scope_ui')
    expect(await screen.findByText('Settlement composition')).toBeInTheDocument()
    expect(screen.getByText('₹195.00')).toBeInTheDocument()
    expect(screen.getAllByText('₹5.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹200.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SETTLEMENT_COMPOSITION_RESIDUAL').length).toBeGreaterThan(0)
  })

  it('filters exception rows client-side without changing source data', async () => {
    mockFetch({ '/exceptions': exceptions })
    renderAt('/exceptions?scope=scope_ui')
    expect((await screen.findAllByText('₹200.00')).length).toBeGreaterThan(0)
    expect(screen.getByText('₹900.00')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Materiality'), { target: { value: 'critical' } })
    expect(screen.queryAllByText('₹200.00')).toHaveLength(0)
    expect(screen.getByText('₹900.00')).toBeInTheDocument()
  })

  it('renders verified Gate 17 and final held-out evaluation metrics directly', async () => {
    mockFetch({ '/api/v1/evaluation': { artifacts: [
      { filename: 'scale-10000-clean.json', schema_version: 'gate17-scale-benchmark-v1', artifact_sha256: 'abc123', config: { settlement_count: 10000 }, hardware: { machine: 'aarch64', python: '3.12.3' }, metrics: { settlements_per_second_proof_pipeline: 206.97, max_rss_kib: 3332736, raw_rows: 1203220 }, status_counts: { proven_reconciled: 8000, residual: 1000 } },
      { filename: 'final-summary.json', schema_version: 'gate19-final-summary-v1', artifact_sha256: 'def456', config: { settlement_count: 768 }, hardware: { machine: 'aarch64', python: '3.12.3' }, metrics: { safe_match_rate: 0.666667, auto_match_precision: 1, truth_reconciled_recall: 0.820513, false_auto_reconciled: 0, non_green_decisions: 256, fuzzy_false_auto_reconciled: 9, source_schema_case_count: 4, source_schema_fail_closed_cases: 4, failure_campaign_check_count: 12, failure_campaign_passed: 12 }, status_counts: { reconciled: 512, residual: 78, unresolved: 170, contradicted: 8 } },
    ] } })
    renderAt('/evaluation?scope=scope_ui')
    expect(await screen.findByText('scale-10000-clean.json')).toBeInTheDocument()
    expect(screen.getByText('206.97 /s')).toBeInTheDocument()
    expect(screen.getByText('1,203,220')).toBeInTheDocument()
    expect(screen.getByText('final-summary.json')).toBeInTheDocument()
    expect(screen.getByText('100.00%')).toBeInTheDocument()
    expect(screen.getByText('82.05%')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.getByText('4/4')).toBeInTheDocument()
    expect(screen.getByText('12/12')).toBeInTheDocument()
  })

  it('renders an explicit integrity/API error state', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: 'artifact digest mismatch' }), { status: 409, headers: { 'Content-Type': 'application/json' } }))))
    renderAt('/?scope=scope_ui')
    expect(await screen.findByText('Evidence view unavailable')).toBeInTheDocument()
    expect(screen.getByText('artifact digest mismatch')).toBeInTheDocument()
  })
})
