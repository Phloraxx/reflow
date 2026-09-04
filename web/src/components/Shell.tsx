import { Activity, FlaskConical, Layers3, ListChecks, PlayCircle, ReceiptText, ShieldCheck } from 'lucide-react'
import { FormEvent, ReactNode, useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useScope } from '../scope'

const nav = [
  ['Live Run', '/demo', PlayCircle],
  ['Overview', '/', Activity],
  ['Proofs', '/proofs', ReceiptText],
  ['Exceptions', '/exceptions', ListChecks],
  ['Sources', '/sources', Layers3],
  ['Evaluation', '/evaluation', FlaskConical],
] as const

export function Shell({ children }: { children: ReactNode }) {
  const { scopeId, setScopeId } = useScope()
  const [draft, setDraft] = useState(scopeId)
  const navigate = useNavigate()
  const location = useLocation()
  const demoMode = location.pathname === "/demo"
  const recordingMode = demoMode && new URLSearchParams(location.search).get("recording") === "1"

  function apply(event: FormEvent) {
    event.preventDefault()
    const next = draft.trim()
    if (!next) return
    setScopeId(next)
    const params = new URLSearchParams(location.search)
    params.set('scope', next)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }

  return <div className={recordingMode ? "app-shell recording-shell" : "app-shell"}>
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark">RF</div>
        <div><strong>ReFlow</strong><span>Settlement reconciliation</span></div>
      </div>
      <nav className="primary-nav" aria-label="Primary navigation">
        {nav.map(([label, path, Icon]) => <NavLink key={path} to={`${path}?scope=${encodeURIComponent(scopeId)}`} end={path === '/'} className={({ isActive }) => isActive ? 'nav-link nav-active' : 'nav-link'}><Icon size={17} /><span>{label}</span></NavLink>)}
      </nav>
      <div className="sidebar-rule" />
      <div className="read-only-note"><ShieldCheck size={17} /><div><strong>Read-only surface</strong><span>Financial truth remains deterministic.</span></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <div className="topbar-title"><span className="eyebrow">{recordingMode ? "ReFlow / Finance close" : demoMode ? "Finance close" : "Operator Control Tower"}</span><strong>{demoMode ? "Settlement verification workspace" : "Evidence, proofs, exceptions"}</strong></div>
        {!demoMode && <form className="scope-form" onSubmit={apply}>
          <label htmlFor="scope-id">Active scope</label>
          <div className="scope-input-wrap"><input id="scope-id" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} /><button type="submit">Apply</button></div>
        </form>}
        <div className="mode-badge"><span className="pulse-dot" />{recordingMode ? "TEST MODE · SYNTHETIC" : demoMode ? "EVALUATION" : "READ ONLY"}</div>
      </header>
      <main className="content">{children}</main>
    </div>
  </div>
}
