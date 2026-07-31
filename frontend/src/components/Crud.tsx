import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ApiError } from '../api/client'
import type { Page } from '../api/client'
import { useApp } from '../state/AppContext'
import { Alert, CheckField, ConfirmButton, Empty, Field, Modal, Spinner } from './ui'

export interface Column<T> {
  key: string
  label: string
  numeric?: boolean
  render?: (row: T) => ReactNode
}

export interface FormField {
  name: string
  label: string
  type?: 'text' | 'number' | 'textarea' | 'checkbox' | 'select' | 'date' | 'color'
  options?: { value: any; label: string }[]
  required?: boolean
  full?: boolean
  hint?: string
  /** Hidden on create, shown on edit, or vice versa. */
  only?: 'create' | 'edit'
  step?: string
}

/** Shared list-fetching hook, so every page handles loading and errors alike. */
export function useList<T>(path: string, params?: Record<string, any>, enabled = true) {
  const [items, setItems] = useState<T[]>([])
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState('')
  const key = JSON.stringify(params ?? {})

  const reload = useCallback(async () => {
    if (!enabled) {
      setItems([])
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await api.get<Page<T> | T[]>(path, { limit: 1000, ...(params ?? {}) })
      setItems(Array.isArray(data) ? data : data.items)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setItems([])
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

  return { items, loading, error, reload, setItems }
}

function emptyValue(field: FormField) {
  if (field.type === 'checkbox') return false
  if (field.type === 'number') return ''
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
              {field.type === 'textarea' ? (
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
    let value = values[field.name]
    if (field.type === 'checkbox') {
      out[field.name] = !!value
      continue
    }
    if (value === '' || value === undefined) {
      out[field.name] = null
      continue
    }
    if (field.type === 'number') {
      const num = Number(value)
      out[field.name] = Number.isNaN(num) ? null : num
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
}) {
  const { canEdit } = useApp()
  const [query, setQuery] = useState('')
  const listParams = useMemo(
    () => ({ ...(params ?? {}), ...(query ? { q: query } : {}) }),
    [params, query],
  )
  const { items, loading, error, reload } = useList<T>(endpoint, listParams)

  const [editing, setEditing] = useState<T | null | 'new'>(null)
  const [values, setValues] = useState<Record<string, any>>({})
  const [saveError, setSaveError] = useState('')
  const [saving, setSaving] = useState(false)

  const allowEdit = canEdit && editable
  const mode: 'create' | 'edit' = editing === 'new' ? 'create' : 'edit'

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
      await reload()
      onChanged?.()
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <div className="toolbar">
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
        <span className="muted small">{items.length} rows</span>
        {allowEdit && (
          <button className="primary" onClick={openNew}>
            New {entityName.toLowerCase()}
          </button>
        )}
      </div>

      <Alert kind="err">{error}</Alert>

      {loading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <Empty>No {entityName.toLowerCase()} records yet.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col.key} className={col.numeric ? 'num' : undefined}>
                    {col.label}
                  </th>
                ))}
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
