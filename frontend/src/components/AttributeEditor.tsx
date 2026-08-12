import { useState } from 'react'
import type { Attribute } from '../api/types'

/**
 * Generic key/value editor, reused for locations and lines.
 *
 * The suggestions below are starting points, not a fixed vocabulary — the
 * whole reason attributes are key/value rows is that a new one should never
 * need a schema change or a release.
 */
export const LOCATION_ATTRIBUTE_SUGGESTIONS = [
  'has_shelter',
  'has_bench',
  'wheelchair_accessible',
  'lit',
  'park_and_ride',
  'platform_count',
  'real_time_display',
  'capacity',
  'fuel_type_supported',
]

/**
 * Pattern attributes describe one *variant* of a line, not the whole line.
 * Their values print as bubbles beside the line number on duty cards and
 * above the column on combined timetables — "127" "EXP".
 */
export const PATTERN_ATTRIBUTE_SUGGESTIONS = [
  'TYPE',
  'SERVICE',
  'peak_only',
  'school_days',
  'via',
  'operator_notes',
]

export const LINE_ATTRIBUTE_SUGGESTIONS = [
  'wheelchair_accessible',
  'peak_only',
  'night_service',
  'seasonal',
  'express',
  'operator_notes',
]

export function AttributeEditor({
  value,
  onChange,
  suggestions = [],
  disabled,
}: {
  value: Attribute[]
  onChange: (next: Attribute[]) => void
  suggestions?: string[]
  disabled?: boolean
}) {
  const [newKey, setNewKey] = useState('')

  function update(index: number, patch: Partial<Attribute>) {
    onChange(value.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function add(key: string) {
    const trimmed = key.trim()
    if (!trimmed) return
    if (value.some((row) => row.attribute_key === trimmed)) return
    onChange([...value, { attribute_key: trimmed, attribute_value: '' }])
    setNewKey('')
  }

  const unused = suggestions.filter((s) => !value.some((row) => row.attribute_key === s))

  return (
    <div>
      {value.length === 0 && (
        <p className="muted small" style={{ marginTop: 0 }}>
          No attributes set.
        </p>
      )}
      {value.map((row, index) => (
        <div className="kv" key={index}>
          <input
            value={row.attribute_key}
            disabled={disabled}
            onChange={(e) => update(index, { attribute_key: e.target.value })}
          />
          <input
            value={row.attribute_value ?? ''}
            disabled={disabled}
            placeholder="value"
            onChange={(e) => update(index, { attribute_value: e.target.value })}
          />
          <button
            className="small danger"
            disabled={disabled}
            onClick={() => onChange(value.filter((_, i) => i !== index))}
            title="Remove"
          >
            ✕
          </button>
        </div>
      ))}

      {!disabled && (
        <>
          <div className="kv" style={{ gridTemplateColumns: '1fr 1fr 60px' }}>
            <input
              placeholder="new attribute key"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  add(newKey)
                }
              }}
            />
            <span />
            <button className="small" onClick={() => add(newKey)}>
              Add
            </button>
          </div>
          {unused.length > 0 && (
            <div className="small muted" style={{ marginTop: 4 }}>
              Suggested:{' '}
              {unused.map((key) => (
                <button
                  key={key}
                  className="small"
                  style={{ marginRight: 4, marginBottom: 4 }}
                  onClick={() => add(key)}
                >
                  + {key}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
