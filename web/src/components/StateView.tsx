import { AlertTriangle, Inbox, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ApiState } from '../api'

export function DataState<T>({ state, empty, children }: { state: ApiState<T>; empty?: (data: T) => boolean; children: (data: T) => ReactNode }) {
  if (state.status === 'loading') {
    return <div className="state-panel"><LoaderCircle className="spin" size={20} /><div><strong>Compiling view</strong><span>Reading immutable finance artifacts…</span></div></div>
  }
  if (state.status === 'error') {
    return <div className="state-panel state-error"><AlertTriangle size={20} /><div><strong>Evidence view unavailable</strong><span>{state.message}</span></div></div>
  }
  if (empty?.(state.data)) {
    return <div className="state-panel"><Inbox size={20} /><div><strong>No evidence in this view</strong><span>Nothing is being inferred to fill the gap.</span></div></div>
  }
  return children(state.data)
}
