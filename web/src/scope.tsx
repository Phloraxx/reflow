import { createContext, useContext } from 'react'

export type ScopeContextValue = {
  scopeId: string
  setScopeId: (scopeId: string) => void
}

export const ScopeContext = createContext<ScopeContextValue | null>(null)

export function useScope(): ScopeContextValue {
  const value = useContext(ScopeContext)
  if (!value) throw new Error('ScopeContext is unavailable')
  return value
}
