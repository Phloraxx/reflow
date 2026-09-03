export function PaginationFooter({
  hasMore,
  loading,
  error,
  onLoadMore,
}: {
  hasMore: boolean
  loading: boolean
  error: string | null
  onLoadMore: () => void
}) {
  if (!hasMore && !error) return null
  return (
    <div className="pagination-footer">
      {error && <span className="pagination-error">{error}</span>}
      {hasMore && (
        <button type="button" onClick={onLoadMore} disabled={loading}>
          {loading ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  )
}
