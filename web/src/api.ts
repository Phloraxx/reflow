import { useEffect, useState } from 'react'

export type ApiState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; data: T }

export function useApi<T>(path: string): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    void fetch(path, { signal: controller.signal, headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as { detail?: string } | null
          throw new Error(body?.detail ?? `Request failed with HTTP ${response.status}`)
        }
        return response.json() as Promise<T>
      })
      .then((data) => setState({ status: 'success', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: 'error',
          message: error instanceof Error ? error.message : 'Unknown API error',
        })
      })
    return () => controller.abort()
  }, [path])

  return state
}

export function scopedPath(scopeId: string, suffix: string): string {
  return `/api/v1/scopes/${encodeURIComponent(scopeId)}${suffix}`
}
