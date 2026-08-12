import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type { Page } from '../api/client'
import { useApp } from '../state/AppContext'
import { EntitySelect, useDebounced } from './EntitySelect'
import { Alert, CheckField, ConfirmButton, Empty, Field, Modal, Spinner } from './ui'

export const PAGE_SIZES = [25, 50, 100, 250]

export interface Column<T> {
  key: string
  label: string
  numeric?: boolean
  /** Column name to sort by server-side. Omit to make the column unsortable. */
  sortKey?: string
  render?: (row: T) => ReactNode
}

export interface FormField {
  name: string
  label: string
  type?:
    | 'text'
    | 'number'
    | 'textarea'
    | 'checkbox'
    | 'select'
    | 'date'
    | 'color'
    /** Server-backed searchable picker; requires `endpoint`. */
    | 'entity'
  options?: { value: any; label: string }[]
  /** For type 'entity': the collection to search, e.g. '/locations'. */
  endpoint?: string
  /** For type 'entity': extra query filters, e.g. `{ location_type: 'stop' }`. */
  entityParams?: Record<string, any>
  required?: boolean
  full?: boolean
  hint?: string
  only?: 'create' | 'edit'
  step?: string
}

/**
 * Load a whole collection.
 *
 * Only for genuinely small reference sets — modes, calendars on one board,
 * a line's patterns. Anything that grows with the size of the network wants
 * `CrudTable` (paged) or `EntitySelect` (searched) instead. `truncated` is
 * exposed so a caller can never mistake a capped list for a complete one.
 */
export function useList<T>(path: string, params?: Record<string, any>, enabled = true) {
  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState('')
  const key = JSON.stringify(params ?? {})
  const cap = (params?.limit as number) ?? 500

  const reload = useCallback(async () => {
    if (!enabled) {
      setItems([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await api.get<Page<T> | T[]>(path, { limit: cap, ...(params ?? {}) })
      const rows = Array.isArray(data) ? data : data.items
      setItems(rows)
      setTotal(Array.isArray(data) ? rows.length : data.total)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
    // `key` stands in for `params` so a fresh object literal each render does
    // not retrigger the fetch forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, key, enabled])

  useEffect(() => {
    reload()
  }, [reload])

  return { items, total, truncated: total > items.length, loading, error, reload, setItems }
}

function emptyValue(field: FormField) {
  if (field.type === 'checkbox') return false
  if (field.type === 'entity') return null
  return ''
}

export function FormFields({
  fields,
  values,
  setValue,
  mode,
}: {
  fields: FormField[]
  values: Record<string, any>
  setValue: (name: string, value: any) => void
  mode: 'create' | 'edit'
}) {
  return (
    <div className="form-grid">
      {fields
        .filter((f) => !f.only || f.only === mode)
        .map((field) => {
          const value = values[field.name]
          if (field.type === 'checkbox') {
            return (
              <div key={field.name} className={field.full ? 'full' : undefined}>
                <CheckField
                  label={field.label}
                  checked={!!value}
                  onChange={(v) => setValue(field.name, v)}
                />
              </div>
            )
          }
          const isFull = field.full || field.type === 'textarea'
          return (
            <Field key={field.name} label={field.label} full={isFull} hint={field.hint}>
              {field.type === 'entity' ? (
                <EntitySelect
                  endpoint={field.endpoint!}
                  params={field.entityParams}
                  value={value === '' || value === undefined ? null : Number(value)}
                  onChange={(id) => setValue(field.name, id)}
                  allowClear={!field.required}
                />
              ) : field.type === 'textarea' ? (
                <textarea
                  value={value ?? ''}
                  onChange={(e) => setValue(field.name, e.target.value)}
                />
              ) : field.type === 'select' ? (
                <select
                  value={value ?? ''}
                  onChange={(e) => setValue(field.name, e.target.value)}
                >
                  <option value="">{field.required ? '— choose —' : '— none —'}</option>
                  {(field.options ?? []).map((opt) => (
                    <option key={String(opt.value)} value={String(opt.value)}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
                  step={field.step}
                  value={value ?? ''}
                  onChange={(e) => setValue(field.name, e.target.value)}
                />
              )}
            </Field>
          )
        })}
    </div>
  )
}

/**
 * Turn form strings back into the types the API expects.
 *
 * Empty select and number inputs come back as "" from the DOM; sending that
 * where the API wants `null` or a number is the single most common source of
 * 422s, so it is normalised in one place.
 */
export function cleanPayload(fields: FormField[], values: Record<string, any>) {
  const out: Record<string, any> = {}
  for (const field of fields) {
    const value = values[field.name]
    if (field.type === 'checkbox') {
      out[field.name] = !!value
      continue
    }
    if (value === '' || value === undefined || value === null) {
      out[field.name] = null
      continue
    }
    if (field.type === 'number') {
      const num = Number(value)
      out[field.name] = Number.isNaN(num) ? null : num
      continue
    }
    if (field.type === 'entity') {
      out[field.name] = Number(value)
      continue
    }
    if (field.type === 'select') {
      // Numeric-looking select values are foreign keys.
      out[field.name] = /^\d+$/.test(String(value)) ? Number(value) : value
      continue
    }
    out[field.name] = value
  }
  return out
}

export function Pager({
  offset,
  limit,
  total,
  loading,
  onOffset,
  onLimit,
}: {
  offset: number
  limit: number
  total: number
  loading?: boolean
  onOffset: (next: number) => void
  onLimit: (next: number) => void
}) {
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, total)
  const canPrev = offset > 0
  const canNext = offset + limit < total

  return (
    <div className="pager">
      <span className="muted small">
        {loading ? 'Loading…' : `Showing ${from.toLocaleString()}–${to.toLocaleString()} of ${total.toLocaleString()}`}
      </span>
      <span className="spacer" />
      <select
        value={limit}
        onChange={(e) => {
          onLimit(Number(e.target.value))
          onOffset(0)
        }}
        title="Rows per page"
      >
        {PAGE_SIZES.map((size) => (
          <option key={size} value={size}>
            {size} / page
          </option>
        ))}
      </select>
      <button className="small" disabled={!canPrev} onClick={() => onOffset(0)} title="First page">
        «
      </button>
      <button
        className="small"
        disabled={!canPrev}
        onClick={() => onOffset(Math.max(0, offset - limit))}
      >
        ‹ Prev
      </button>
      <button className="small" disabled={!canNext} onClick={() => onOffset(offset + limit)}>
        Next ›
      </button>
      <button
        className="small"
        disabled={!canNext}
        onClick={() => onOffset(Math.max(0, (Math.ceil(total / limit) - 1) * limit))}
        title="Last page"
      >
        »
      </button>
    </div>
  )
}

export function CrudTable<T extends Record<string, any>>({
  endpoint,
  columns,
  fields,
  entityName,
  params,
  searchable = true,
  defaults,
  toPayload,
  onChanged,
  extraRowActions,
  toolbarExtra,
  idKey = 'id',
  wideModal,
  editable = true,
  defaultPageSize = 50,
  refreshToken,
}: {
  endpoint: string
  columns: Column<T>[]
  fields: FormField[]
  entityName: string
  params?: Record<string, any>
  searchable?: boolean
  defaults?: Record<string, any>
  toPayload?: (values: Record<string, any>, mode: 'create' | 'edit') => Record<string, any>
  onChanged?: () => void
  extraRowActions?: (row: T) => ReactNode
  toolbarExtra?: ReactNode
  idKey?: string
  wideModal?: boolean
  editable?: boolean
  defaultPageSize?: number
  /**
   * Bump this to force a refetch after something *outside* the table changed
   * a row — a pattern's stop list, a block's pieces, a location's attributes.
   * Those are edited in their own modals, so the table has no way to know its
   * `stop_count` or `piece_count` just went stale, and the row would keep
   * showing the old value (and hand the old data back to the editor) until
   * the page was reloaded.
   */
  refreshToken?: number | string
}) {
  const { canEdit } = useApp()
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query)
  const [limit, setLimit] = useState(defaultPageSize)
  const [offset, setOffset] = useState(0)
  const [sort, setSort] = useState<string | null>(null)
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')

  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const paramKey = JSON.stringify(params ?? {})

  // A new search must not leave you on page 9 of the old result set.
  useEffect(() => {
    setOffset(0)
  }, [debouncedQuery, paramKey])

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get<Page<T>>(endpoint, {
        ...(params ?? {}),
        ...(debouncedQuery ? { q: debouncedQuery } : {}),
        ...(sort ? { sort, order } : {}),
        limit,
        offset,
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, paramKey, debouncedQuery, sort, order, limit, offset, refreshToken])

  useEffect(() => {
    reload()
  }, [reload])

  const [editing, setEditing] = useState<T | null | 'new'>(null)
  const [values, setValues] = useState<Record<string, any>>({})
  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)

  const allowEdit = canEdit && editable
  const mode: 'create' | 'edit' = editing === 'new' ? 'create' : 'edit'

  function toggleSort(column: Column<T>) {
    const key = column.sortKey ?? column.key
    if (sort === key) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(key)
      setOrder('asc')
    }
    setOffset(0)
  }

  function openNew() {
    const initial: Record<string, any> = {}
    for (const field of fields) initial[field.name] = emptyValue(field)
    setValues({ ...initial, ...(defaults ?? {}) })
    setSaveError('')
    setEditing('new')
  }

  function openEdit(row: T) {
    const initial: Record<string, any> = {}
    for (const field of fields) {
      const raw = (row as any)[field.name]
      initial[field.name] = raw === null || raw === undefined ? emptyValue(field) : raw
    }
    setValues(initial)
    setSaveError('')
    setEditing(row)
  }

  async function save() {
    setSaving(true)
    setSaveError('')
    try {
      const base = cleanPayload(fields, values)
      const payload = toPayload ? toPayload(base, mode) : base
      if (editing === 'new') await api.post(endpoint, payload)
      else await api.patch(`${endpoint}/${(editing as any)[idKey]}`, payload)
      setEditing(null)
      await reload()
      onChanged?.()
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  async function remove(row: T) {
    try {
      await api.del(`${endpoint}/${(row as any)[idKey]}`)
      // Deleting the only row on the last page would otherwise strand you on
      // an empty view.
      if (items.length === 1 && offset > 0) setOffset(Math.max(0, offset - limit))
      else await reload()
      onChanged?.()
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <div className="toolbar-row">
        {searchable && (
          <input
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ minWidth: 220 }}
          />
        )}
        {toolbarExtra}
        <span className="spacer" />
        {allowEdit && (
          <button className="primary" onClick={openNew}>
            New {entityName.toLowerCase()}
          </button>
        )}
      </div>

      <Alert kind="err">{error}</Alert>

      {loading && items.length === 0 ? (
        <Spinner />
      ) : items.length === 0 ? (
        <Empty>
          {debouncedQuery
            ? `No ${entityName.toLowerCase()} matches “${debouncedQuery}”.`
            : `No ${entityName.toLowerCase()} records yet.`}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                {columns.map((col) => {
                  const key = col.sortKey ?? col.key
                  const sortable = col.sortKey !== undefined
                  const active = sort === key
                  return (
                    <th
                      key={col.key}
                      className={`${col.numeric ? 'num' : ''}${sortable ? ' sortable' : ''}`}
                      onClick={sortable ? () => toggleSort(col) : undefined}
                      title={sortable ? 'Sort by this column' : undefined}
                    >
                      {col.label}
                      {active && <span className="sort-arrow">{order === 'asc' ? ' ▲' : ' ▼'}</span>}
                    </th>
                  )
                })}
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={String((row as any)[idKey])}>
                  {columns.map((col) => (
                    <td key={col.key} className={col.numeric ? 'num' : undefined}>
                      {col.render ? col.render(row) : formatCell((row as any)[col.key])}
                    </td>
                  ))}
                  <td className="actions">
                    {extraRowActions?.(row)}{' '}
                    {allowEdit && (
                      <>
                        <button className="small" onClick={() => openEdit(row)}>
                          Edit
                        </button>{' '}
                        <ConfirmButton
                          onConfirm={() => remove(row)}
                          question={`Delete this ${entityName.toLowerCase()}?`}
                        />
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Pager
        offset={offset}
        limit={limit}
        total={total}
        loading={loading}
        onOffset={setOffset}
        onLimit={setLimit}
      />

      {editing && (
        <Modal
          wide={wideModal}
          title={editing === 'new' ? `New ${entityName.toLowerCase()}` : `Edit ${entityName.toLowerCase()}`}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button onClick={() => setEditing(null)}>Cancel</button>
              <button className="primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          }
        >
          <Alert kind="err">{saveError}</Alert>
          <FormFields
            fields={fields}
            values={values}
            mode={mode}
            setValue={(name, value) => setValues((v) => ({ ...v, [name]: value }))}
          />
        </Modal>
      )}
    </>
  )
}

function formatCell(value: any): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="muted">—</span>
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? `${value.length}` : <span className="muted">—</span>
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
