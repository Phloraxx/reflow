import { useCallback, useEffect, useRef, useState } from 'react'

export type ApiState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; data: T }

export type PagedResponse<T> = {
  items: T[]
  next_cursor: string | null
}

export type PagedApiState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | {
      status: 'success'
      data: T[]
      nextCursor: string | null
      loadingMore: boolean
      loadMoreError: string | null
    }

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(body?.detail ?? `Request failed with HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unknown API error'
}

function pagePath(path: string, pageSize: number, cursor: string | null): string {
  const query = new URLSearchParams({ limit: String(pageSize) })
  if (cursor) query.set('cursor', cursor)
  return `${path}?${query.toString()}`
}

export function useApi<T>(path: string): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    void fetch(path, { signal: controller.signal, headers: { Accept: 'application/json' } })
      .then((response) => responseJson<T>(response))
      .then((data) => setState({ status: 'success', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [path])

  return state
}

export function usePagedApi<T>(
  path: string,
  pageSize = 50,
): { state: PagedApiState<T>; loadMore: () => void } {
  const [state, setState] = useState<PagedApiState<T>>({ status: 'loading' })
  const generation = useRef(0)
  const loadMoreController = useRef<AbortController | null>(null)

  useEffect(() => {
    loadMoreController.current?.abort()
    loadMoreController.current = null
    const controller = new AbortController()
    generation.current += 1
    const currentGeneration = generation.current
    setState({ status: 'loading' })
    void fetch(pagePath(path, pageSize, null), {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    })
      .then((response) => responseJson<PagedResponse<T>>(response))
      .then((page) => {
        if (generation.current !== currentGeneration) return
        setState({
          status: 'success',
          data: page.items,
          nextCursor: page.next_cursor,
          loadingMore: false,
          loadMoreError: null,
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || generation.current !== currentGeneration) return
        setState({ status: 'error', message: errorMessage(error) })
      })
    return () => {
      controller.abort()
      loadMoreController.current?.abort()
      loadMoreController.current = null
    }
  }, [pageSize, path])

  const loadMore = useCallback(() => {
    if (state.status !== 'success' || !state.nextCursor || state.loadingMore) return
    const currentGeneration = generation.current
    const cursor = state.nextCursor
    const controller = new AbortController()
    loadMoreController.current?.abort()
    loadMoreController.current = controller
    setState({ ...state, loadingMore: true, loadMoreError: null })
    void fetch(pagePath(path, pageSize, cursor), {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    })
      .then((response) => responseJson<PagedResponse<T>>(response))
      .then((page) => {
        if (controller.signal.aborted || generation.current !== currentGeneration) return
        loadMoreController.current = null
        setState((current) => {
          if (current.status !== 'success') return current
          return {
            status: 'success',
            data: [...current.data, ...page.items],
            nextCursor: page.next_cursor,
            loadingMore: false,
            loadMoreError: null,
          }
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || generation.current !== currentGeneration) return
        loadMoreController.current = null
        setState((current) =>
          current.status === 'success'
            ? { ...current, loadingMore: false, loadMoreError: errorMessage(error) }
            : current,
        )
      })
  }, [pageSize, path, state])

  return { state, loadMore }
}

export function scopedPath(scopeId: string, suffix: string): string {
  return `/api/v1/scopes/${encodeURIComponent(scopeId)}${suffix}`
}
