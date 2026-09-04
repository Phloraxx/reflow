export type Money = {
  amount_paise: string
  currency: string
  display: string
}

export type SourceLabItem = {
  manifest_id: string
  source_kind: string
  completeness: string
  received_late: boolean
  delivery_mode: string
  expected_by: string
  received_at: string | null
  watermark_at: string | null
  adapter_version: string
  schema_fingerprint: string
  delivered_envelope_count: number
  effective_envelope_count: number
}

export type ProofStatusSummary = {
  status: string
  count: number
  amount: Money
}

export type Overview = {
  scope_id: string
  has_current_run: boolean
  run: null | {
    run_id: string
    outcome: string
    period_start: string
    period_end: string
    reporting_timezone: string
    knowledge_cutoff: string
    completed_at: string
    code_build_sha: string | null
    close_readiness_id: string
    close_status: string
    close_reason_codes: string[]
    coverage_certificate_id: string
    coverage_status: string
    orphan_count: number
    orphan_known_value: Money
    balance_control_id: string
    balance_status: string
    balance_residual: Money
  }
  proof_status: ProofStatusSummary[]
  sources: SourceLabItem[]
  active_exception_count: number
  active_exception_value: Money | null
}

export type ProofListItem = {
  proof_id: string
  settlement_id: string
  version: number
  status: string
  settlement_amount: Money
  reason_codes: string[]
  knowledge_cutoff: string
  generated_at: string
  reopened: boolean
}

export type ProofDetail = {
  proof_id: string
  settlement_id: string
  version: number
  status: string
  reason_codes: string[]
  reopened: boolean
  prior_version_id: string | null
  knowledge_cutoff: string
  generated_at: string
  source_envelope_ids: string[]
  composition: {
    status: string
    settlement_amount: Money
    observed_composition: Money
    residual: Money
    component_ids: string[]
    source_envelope_ids: string[]
    reason_codes: string[]
  }
  bank: {
    status: string
    settlement_utr: string | null
    expected_amount: Money
    observed_bank_credit: Money
    residual: Money
    bank_entry_ids: string[]
    source_envelope_ids: string[]
    reason_codes: string[]
  }
  version_timeline: ProofListItem[]
}

export type ExceptionItem = {
  case_id: string
  settlement_id: string
  latest_observation_id: string
  latest_proof_version_id: string
  financial_status: string
  materiality_band: string
  affected_amount: Money
  workflow_status: string
  resolution: string | null
  owner: string | null
  incident_fingerprint_id: string
  incident_cluster_id: string | null
  source_blockers: string[]
  first_seen_at: string
  last_seen_at: string
  age_seconds: number
  observation_count: number
  disposition_count: number
  superseded_by_case_id: string | null
  is_active: boolean
}

export type CaseFile = {
  case: ExceptionItem
  observations: Array<{
    observation_id: string
    run_id: string
    proof_version_id: string
    financial_status: string
    reason_codes: string[]
    affected_amount: Money
    materiality_band: string
    incident_fingerprint_id: string
    source_states: Array<{
      source_kind: string
      completeness: string
      received_late: boolean
      manifest_id: string
    }>
    observed_at: string
  }>
  dispositions: Array<{
    disposition_id: string
    sequence: number
    actor_id: string
    occurred_at: string
    kind: string
    owner: string | null
    note: string | null
  }>
  proof: ProofDetail
  investigation: null | {
    investigation_id: string
    status: string
    next_action: string
    hypothesis: string | null
    citations: string[]
    request_source_kind: string | null
    rejection_reason: string | null
    as_of: string
    trace_count: number
  }
}

export type EvaluationLab = {
  artifacts: Array<{
    filename: string
    schema_version: string
    artifact_sha256: string
    config: Record<string, unknown>
    hardware: Record<string, unknown>
    metrics: Record<string, unknown>
    status_counts: Record<string, unknown> | null
  }>
}


export type JudgeDemoStage = {
  key: string
  label: string
  duration_ms: number
  facts: string[]
}

export type JudgeDemoOutcome = {
  settlement_id: string
  label: string
  amount_paise: number
  amount_display: string
  status: string
  composition_status: string
  bank_status: string
  residual_paise: number
  residual_display: string
  proof_id: string
  version: number
}

export type JudgeDemoStatus = {
  enabled: boolean
  phase: 'ready' | 'initial_run' | 'bank_arrived' | 'reconciled'
  scope_id: string
  focus_case_id: string | null
  focus_proof_id: string | null
  raw_record_count: number
  settlement_count: number
  outcomes: JudgeDemoOutcome[]
  can_run: boolean
  can_add_bank: boolean
  can_rerun: boolean
}

export type JudgeDemoActionResult = {
  phase: JudgeDemoStatus['phase']
  scope_id: string
  stages: JudgeDemoStage[]
  outcomes: JudgeDemoOutcome[]
  focus_case_id: string | null
  focus_proof_id: string | null
  message: string
}
