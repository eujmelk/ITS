import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Page } from '../api/client'

/**
 * Searchable picker backed by the server.
 *
 * The alternative — loading every row and rendering one `<option>` per record
 * — falls over twice on a real network: once on the request (a `limit=1000`
 * that silently truncates), and once on the DOM, because the block editor
 * puts one of these on every piece row. Here each picker holds at most
 * `PAGE_SIZE` options, and only while it is open.
 */

const PAGE_SIZE = 25
const DEBOUNCE_MS = 250

/**
 * Resolved labels, shared across every instance and kept for the life of the
 * page. Twenty block pieces pointing at the same depot is one request, not
 * twenty, and re-opening the editor costs nothing.
 */
const labelCache = new Map<string, string>()

export function cacheEntityLabel(endpoint: string, id: number, label: string) {
  labelCache.set(`${endpoint}:${id}`, label)
}

export function useDebounced<T>(value: T, delay = DEBOUNCE_MS): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export interface EntitySelectProps {
  endpoint: string
  value: number | null | undefined
  onChange: (id: number | null) => void
  /** How to label a row. Defaults to `name`, then `short_name`, then the id. */
  labelOf?: (row: any) => string
  /** Optional second line in the dropdown. */
  sublabelOf?: (row: any) => string | null
  /** Extra query parameters, e.g. `{ location_type: 'stop' }`. */
  params?: Record<string, any>
  placeholder?: string
  disabled?: boolean
  allowClear?: boolean
  autoFocus?: boolean
}

function defaultLabel(row: any): string {
  return row?.name ?? row?.short_name ?? row?.fleet_number ?? row?.code ?? `#${row?.id}`
}

export function EntitySelect({
  endpoint,
  value,
  onChange,
  labelOf = defaultLabel,
  sublabelOf,
  params,
  placeholder = 'Search…',
  disabled,
  allowClear = true,
  autoFocus,
}: EntitySelectProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const [resolved, setResolved] = useState<string | null>(null)

  const debouncedQuery = useDebounced(query)
  const containerRef = useRef<HTMLDivElement>(null)
  const paramKey = JSON.stringify(params ?? {})

  // Resolve the label for a value we were handed but have not searched for.
  useEffect(() => {
    if (value === null || value === undefined) {
      setResolved(null)
      return
    }
    const key = `${endpoint}:${value}`
    const cached = labelCache.get(key)
    if (cached) {
      setResolved(cached)
      return
    }
    let cancelled = false
    api
      .get<any>(`${endpoint}/${value}`)
      .then((row) => {
        const label = labelOf(row)
        labelCache.set(key, label)
        if (!cancelled) setResolved(label)
      })
      .catch(() => {
        // Deleted, or not visible to this user: show the raw id rather than
        // an empty box that looks like nothing is selected.
        if (!cancelled) setResolved(`#${value}`)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, value])

  const search = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<Page<any> | any[]>(endpoint, {
        limit: PAGE_SIZE,
        ...(params ?? {}),
        ...(debouncedQuery ? { q: debouncedQuery } : {}),
      })
      const items = Array.isArray(data) ? data : data.items
      setRows(items)
      setTotal(Array.isArray(data) ? items.length : data.total)
      setHighlight(0)
      for (const row of items) {
        if (row?.id != null) labelCache.set(`${endpoint}:${row.id}`, labelOf(row))
      }
    } catch {
      setRows([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, debouncedQuery, paramKey])

  useEffect(() => {
    if (open) search()
  }, [open, search])

  // Close when the click lands anywhere else.
  useEffect(() => {
    if (!open) return
    function onDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function pick(row: any) {
    labelCache.set(`${endpoint}:${row.id}`, labelOf(row))
    setResolved(labelOf(row))
    onChange(row.id)
    setOpen(false)
    setQuery('')
  }

  const display = useMemo(() => {
    if (open) return query
    return resolved ?? ''
  }, [open, query, resolved])

  return (
    <div className="entity-select" ref={containerRef}>
      <div className="entity-select-control">
        <input
          value={display}
          disabled={disabled}
          autoFocus={autoFocus}
          placeholder={value ? undefined : placeholder}
          onFocus={() => !disabled && setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value)
            if (!open) setOpen(true)
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setOpen(true)
              setHighlight((h) => Math.min(h + 1, rows.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setHighlight((h) => Math.max(h - 1, 0))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              if (open && rows[highlight]) pick(rows[highlight])
            } else if (e.key === 'Escape') {
              setOpen(false)
              setQuery('')
            }
          }}
        />
        {allowClear && value != null && !disabled && (
          <button
            type="button"
            className="entity-select-clear"
            title="Clear"
            onClick={() => {
              onChange(null)
              setResolved(null)
              setQuery('')
            }}
          >
            ✕
          </button>
        )}
      </div>

      {open && (
        <div className="entity-select-menu">
          {loading && <div className="entity-select-note">Searching…</div>}
          {!loading && rows.length === 0 && (
            <div className="entity-select-note">No matches.</div>
          )}
          {rows.map((row, index) => (
            <div
              key={row.id}
              className={`entity-select-option${index === highlight ? ' active' : ''}`}
              onMouseEnter={() => setHighlight(index)}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(row)
              }}
            >
              <div>{labelOf(row)}</div>
              {sublabelOf && sublabelOf(row) && (
                <div className="entity-select-sub">{sublabelOf(row)}</div>
              )}
            </div>
          ))}
          {total > rows.length && (
            <div className="entity-select-note">
              Showing {rows.length} of {total.toLocaleString()} — keep typing to narrow.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
