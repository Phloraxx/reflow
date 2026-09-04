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

  function apply(event: FormEvent) {
    event.preventDefault()
    const next = draft.trim()
    if (!next) return
    setScopeId(next)
    const params = new URLSearchParams(location.search)
    params.set('scope', next)
    navigate(`${location.pathname}?${params.toString()}`, { replace: true })
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark">RF</div>
        <div><strong>ReFlow</strong><span>Finance truth compiler</span></div>
      </div>
      <nav className="primary-nav" aria-label="Primary navigation">
        {nav.map(([label, path, Icon]) => <NavLink key={path} to={`${path}?scope=${encodeURIComponent(scopeId)}`} end={path === '/'} className={({ isActive }) => isActive ? 'nav-link nav-active' : 'nav-link'}><Icon size={17} /><span>{label}</span></NavLink>)}
      </nav>
      <div className="sidebar-rule" />
      <div className="read-only-note"><ShieldCheck size={17} /><div><strong>Read-only surface</strong><span>Financial truth remains deterministic.</span></div></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <div className="topbar-title"><span className="eyebrow">{demoMode ? "Finance close" : "Operator Control Tower"}</span><strong>{demoMode ? "Synthetic workload · real proof engine" : "Evidence, proofs, exceptions"}</strong></div>
        {!demoMode && <form className="scope-form" onSubmit={apply}>
          <label htmlFor="scope-id">Active scope</label>
          <div className="scope-input-wrap"><input id="scope-id" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false} /><button type="submit">Apply</button></div>
        </form>}
        <div className="mode-badge"><span className="pulse-dot" />{demoMode ? "EVALUATION" : "READ ONLY"}</div>
      </header>
      <main className="content">{children}</main>
    </div>
  </div>
}
