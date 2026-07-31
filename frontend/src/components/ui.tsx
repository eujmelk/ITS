import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { ValidationIssue, ValidationReport } from '../api/types'

/* ------------------------------------------------------------------ page */

export function PageHead({
  title,
  intro,
  actions,
}: {
  title: string
  intro?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="page-head">
      <div>
        <h2>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Panel({
  title,
  hint,
  actions,
  children,
}: {
  title?: string
  hint?: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="panel">
      {(title || actions) && (
        <h3 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>
            {title}
            {hint && <span className="hint">{hint}</span>}
          </span>
          {actions}
        </h3>
      )}
      {children}
    </div>
  )
}

export function Alert({ kind, children }: { kind: 'err' | 'ok' | 'info'; children: ReactNode }) {
  if (!children) return null
  return (
    <div className={`alert ${kind}`} style={{ whiteSpace: 'pre-wrap' }}>
      {children}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return <div className="empty">{label}</div>
}

/* ----------------------------------------------------------------- modal */

export function Modal({
  title,
  wide,
  onClose,
  footer,
  children,
}: {
  title: string
  wide?: boolean
  onClose: () => void
  footer?: ReactNode
  children: ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? ' wide' : ''}`}>
        <header>
          <h3>{title}</h3>
          <button className="small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  )
}

export function ConfirmButton({
  onConfirm,
  label = 'Delete',
  question = 'Delete this record? This cannot be undone.',
  className = 'danger small',
}: {
  onConfirm: () => void
  label?: string
  question?: string
  className?: string
}) {
  return (
    <button
      className={className}
      onClick={() => {
        if (window.confirm(question)) onConfirm()
      }}
    >
      {label}
    </button>
  )
}

/* ---------------------------------------------------------------- fields */

export function Field({
  label,
  children,
  full,
  hint,
}: {
  label: string
  children: ReactNode
  full?: boolean
  hint?: string
}) {
  return (
    <div className={`field${full ? ' full' : ''}`}>
      <label>
        {label}
        {hint && <span className="muted"> — {hint}</span>}
      </label>
      {children}
    </div>
  )
}

export function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="field inline">
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      <label>{label}</label>
    </div>
  )
}

/**
 * Service-day time input. Accepts "8:15", "08:15", "08:15:00" and values past
 * midnight such as "25:10" — the backend stores seconds from the start of the
 * service day, so a late trip is not the same as an early one.
 */
export function TimeInput({
  value,
  onChange,
  placeholder = 'HH:MM',
}: {
  value: string | null
  onChange: (v: string) => void
  placeholder?: string
}) {
  const [text, setText] = useState(value ?? '')
  useEffect(() => setText(value ?? ''), [value])
  const valid = text === '' || /^\d{1,2}:\d{2}(:\d{2})?$/.test(text.trim())
  return (
    <input
      value={text}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => onChange(text.trim())}
      style={valid ? undefined : { borderColor: 'var(--err)' }}
      title={valid ? '' : 'Expected HH:MM or HH:MM:SS'}
    />
  )
}

/* ------------------------------------------------------------ validation */

export function IssueList({ report }: { report: ValidationReport | null }) {
  if (!report) return null
  if (!report.issues.length)
    return <div className="alert ok">No problems found.</div>
  return (
    <div>
      {report.issues.map((issue: ValidationIssue, index: number) => (
        <div key={index} className={`issue ${issue.severity}`}>
          {issue.message} <code>{issue.code}</code>
        </div>
      ))}
    </div>
  )
}

/* ----------------------------------------------------------------- misc */

export function secondsToHhmm(value: string | null | undefined): string {
  if (!value) return ''
  const parts = value.split(':')
  if (parts.length < 2) return value
  return `${parts[0]}:${parts[1]}`
}

export function money(cents: number | null | undefined, currency = 'EUR'): string {
  if (cents === null || cents === undefined) return ''
  return `${(cents / 100).toFixed(2)} ${currency}`
}

export function durationLabel(from?: string | null, to?: string | null): string {
  if (!from || !to) return ''
  const toSec = (t: string) => {
    const [h, m, s] = t.split(':').map(Number)
    return h * 3600 + m * 60 + (s || 0)
  }
  const minutes = Math.round((toSec(to) - toSec(from)) / 60)
  if (minutes < 0) return ''
  const hours = Math.floor(minutes / 60)
  return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`
}
