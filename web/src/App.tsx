import { useMemo, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { CaseFilePage } from './pages/CaseFilePage'
import { EvaluationPage } from './pages/EvaluationPage'
import { ExceptionsPage } from './pages/ExceptionsPage'
import { OverviewPage } from './pages/OverviewPage'
import { ProofDetailPage } from './pages/ProofDetailPage'
import { ProofsPage } from './pages/ProofsPage'
import { SourcesPage } from './pages/SourcesPage'
import { ScopeContext } from './scope'

function initialScope(): string {
  const fromUrl = new URLSearchParams(window.location.search).get('scope')
  return fromUrl || import.meta.env.VITE_REFLOW_SCOPE_ID || 'scope_demo'
}

export function App() {
  const [scopeId, setScopeId] = useState(initialScope)
  const scope = useMemo(() => ({ scopeId, setScopeId }), [scopeId])
  return <ScopeContext.Provider value={scope}><Shell><Routes><Route path="/" element={<OverviewPage />} /><Route path="/proofs" element={<ProofsPage />} /><Route path="/proofs/:proofId" element={<ProofDetailPage />} /><Route path="/exceptions" element={<ExceptionsPage />} /><Route path="/cases/:caseId" element={<CaseFilePage />} /><Route path="/sources" element={<SourcesPage />} /><Route path="/evaluation" element={<EvaluationPage />} /><Route path="*" element={<Navigate to={`/?scope=${encodeURIComponent(scopeId)}`} replace />} /></Routes></Shell></ScopeContext.Provider>
}
