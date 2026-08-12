import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Line, Location, Pattern, PatternStop } from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import type { Column, FormField } from '../components/Crud'
import {
  AttributeEditor,
  LINE_ATTRIBUTE_SUGGESTIONS,
  PATTERN_ATTRIBUTE_SUGGESTIONS,
} from '../components/AttributeEditor'
import { EntitySelect } from '../components/EntitySelect'
import { MapView } from '../components/MapView'
import { Alert, Empty, Field, Modal, PageHead, Panel, Spinner } from '../components/ui'
import { useApp } from '../state/AppContext'

const MODES = ['bus', 'tram', 'metro', 'rail', 'ferry', 'other']

export default function LinesPage() {
  const { canEdit } = useApp()
  const [selectedLine, setSelectedLine] = useState<Line | null>(null)
  // Attributes are edited in a modal, so the table is told when the summary
  // column it shows has gone stale.
  const [linesToken, setLinesToken] = useState(0)
  // CrudTable owns its own paged fetch; nothing else on this page needs the
  // full list of lines.
  const columns: Column<Line>[] = [
    {
      key: 'short_name',
      label: 'Line',
      sortKey: 'short_name',
      render: (row) => (
        <span
          className="tag"
          style={{
            background: row.color ? `#${row.color}` : undefined,
            color: row.text_color ? `#${row.text_color}` : undefined,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {row.short_name}
        </span>
      ),
    },
    { key: 'long_name', label: 'Name' },
    { key: 'mode', label: 'Mode' },
    { key: 'pattern_count', label: 'Patterns', numeric: true },
    {
      key: 'is_active',
      label: 'Status',
      render: (row) =>
        row.is_active ? <span className="tag ok">active</span> : <span className="tag grey">inactive</span>,
    },
    {
      key: 'attributes',
      label: 'Attributes',
      render: (row) =>
        row.attributes?.length ? (
          <span className="small">
            {row.attributes.map((a) => `${a.attribute_key}=${a.attribute_value ?? ''}`).join(', ')}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ]

  const fields: FormField[] = [
    { name: 'short_name', label: 'Short name', required: true, hint: 'as shown on the vehicle' },
    { name: 'long_name', label: 'Long name' },
    { name: 'mode', label: 'Mode', type: 'select', options: MODES.map((m) => ({ value: m, label: m })) },
    { name: 'sort_order', label: 'Sort order', type: 'number' },
    { name: 'color', label: 'Colour', hint: '6 hex digits, no #' },
    { name: 'text_color', label: 'Text colour', hint: '6 hex digits, no #' },
    { name: 'is_active', label: 'Active', type: 'checkbox' },
    { name: 'description', label: 'Description', type: 'textarea' },
  ]

  return (
    <>
      <PageHead
        title="Lines & patterns"
        intro="A line carries generic key/value attributes, and one or more patterns — the ordered stop sequences its trips follow."
      />

      <Panel>
        <CrudTable<Line>
          endpoint="/lines"
          entityName="Line"
          columns={columns}
          fields={fields}
          defaults={{ mode: 'bus', is_active: true, sort_order: 0 }}
          refreshToken={linesToken}
          extraRowActions={(row) => (
            <>
              <button className="small" onClick={() => setSelectedLine(row)}>
                Patterns
              </button>{' '}
              {canEdit && (
                <LineAttributesButton
                  line={row}
                  onSaved={() => setLinesToken((n) => n + 1)}
                />
              )}
            </>
          )}
        />
      </Panel>

      {selectedLine && (
        <PatternsPanel line={selectedLine} onClose={() => setSelectedLine(null)} />
      )}
    </>
  )
}

function LineAttributesButton({ line, onSaved }: { line: Line; onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState(line.attributes ?? [])
  const [error, setError] = useState('')

  async function save() {
    setError('')
    try {
      await api.patch(`/lines/${line.id}`, {
        attributes: rows
          .filter((r) => r.attribute_key.trim())
          .map((r) => ({ attribute_key: r.attribute_key.trim(), attribute_value: r.attribute_value })),
      })
      setOpen(false)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <button
        className="small"
        onClick={() => {
          setRows(line.attributes ?? [])
          setOpen(true)
        }}
      >
        Attributes
      </button>
      {open && (
        <Modal
          title={`Attributes — line ${line.short_name}`}
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" onClick={save}>
                Save
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <AttributeEditor value={rows} onChange={setRows} suggestions={LINE_ATTRIBUTE_SUGGESTIONS} />
        </Modal>
      )}
    </>
  )
}

/* -------------------------------------------------------------- patterns */

function PatternsPanel({ line, onClose }: { line: Line; onClose: () => void }) {
  const { canEdit } = useApp()
  const params = useMemo(() => ({ line_id: line.id }), [line.id])
  const [editingStops, setEditingStops] = useState<Pattern | null>(null)
  // Editing a pattern's stops happens in a modal the table knows nothing
  // about, so the table is told explicitly to refetch afterwards.
  const [refreshToken, setRefreshToken] = useState(0)
  const reload = () => setRefreshToken((n) => n + 1)

  return (
    <Panel
      title={`Patterns — line ${line.short_name}`}
      actions={
        <button className="small" onClick={onClose}>
          Close
        </button>
      }
    >
      <CrudTable<Pattern>
        endpoint="/patterns"
        entityName="Pattern"
        params={params}
        searchable={false}
        refreshToken={refreshToken}
        defaults={{ line_id: line.id, direction: 0 }}
        columns={[
          { key: 'name', label: 'Pattern' },
          {
            key: 'direction',
            label: 'Direction',
            render: (row) => (row.direction === 0 ? 'Outbound (0)' : 'Inbound (1)'),
          },
          {
            key: 'badges',
            label: 'Attributes',
            render: (row) =>
              row.badges?.length ? (
                <>
                  {row.badges.map((badge) => (
                    <span className="bubble" key={badge}>
                      {badge}
                    </span>
                  ))}
                </>
              ) : (
                <span className="muted">—</span>
              ),
          },
          { key: 'headsign', label: 'Headsign' },
          { key: 'stop_count', label: 'Stops', numeric: true },
          {
            key: 'total_run_seconds',
            label: 'Default run',
            numeric: true,
            render: (row) => `${Math.round(row.total_run_seconds / 60)} min`,
          },
        ]}
        fields={[
          { name: 'name', label: 'Name', required: true },
          {
            name: 'direction',
            label: 'Direction',
            type: 'select',
            options: [
              { value: 0, label: 'Outbound (0)' },
              { value: 1, label: 'Inbound (1)' },
            ],
          },
          { name: 'headsign', label: 'Headsign', hint: 'default for trips on this pattern' },
          { name: 'is_primary', label: 'Primary pattern', type: 'checkbox' },
          { name: 'notes', label: 'Notes', type: 'textarea' },
        ]}
        toPayload={(values, mode) => (mode === 'create' ? { ...values, line_id: line.id } : values)}
        extraRowActions={(row) => (
          <>
            <button className="small" onClick={() => setEditingStops(row)}>
              Stops ({row.stop_count})
            </button>{' '}
            {canEdit && <PatternAttributesButton pattern={row} onSaved={reload} />}{' '}
            {canEdit && (
              <button
                className="small"
                title="Copy this pattern, stops included"
                onClick={async () => {
                  try {
                    await api.post(`/patterns/${row.id}/duplicate`)
                    reload()
                  } catch (e) {
                    window.alert(e instanceof ApiError ? e.message : String(e))
                  }
                }}
              >
                Copy
              </button>
            )}
          </>
        )}
      />

      {editingStops && (
        <PatternStopsEditor
          pattern={editingStops}
          onClose={() => setEditingStops(null)}
          onSaved={reload}
        />
      )}
    </Panel>
  )
}

function PatternAttributesButton({
  pattern,
  onSaved,
}: {
  pattern: Pattern
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState(pattern.attributes ?? [])
  const [error, setError] = useState('')

  async function save() {
    setError('')
    try {
      await api.patch(`/patterns/${pattern.id}`, {
        attributes: rows
          .filter((r) => r.attribute_key.trim())
          .map((r) => ({
            attribute_key: r.attribute_key.trim(),
            attribute_value: r.attribute_value,
          })),
      })
      setOpen(false)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <button
        className="small"
        title="Attributes shown as bubbles on duty cards and timetables"
        onClick={() => {
          setRows(pattern.attributes ?? [])
          setOpen(true)
        }}
      >
        Attributes
      </button>
      {open && (
        <Modal
          title={`Attributes — ${pattern.name}`}
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" onClick={save}>
                Save
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <p className="small muted" style={{ marginTop: 0 }}>
            These describe this <em>variant</em> of the line, not the whole
            line. Each non-empty <strong>value</strong> prints as a bubble
            beside the line number — set <code>TYPE</code> to <code>EXP</code>{' '}
            and a duty card shows{' '}
            <span className="bubble">127</span>
            <span className="bubble">EXP</span>.
          </p>
          <AttributeEditor
            value={rows}
            onChange={setRows}
            suggestions={PATTERN_ATTRIBUTE_SUGGESTIONS}
          />
        </Modal>
      )}
    </>
  )
}

function PatternStopsEditor({
  pattern,
  onClose,
  onSaved,
}: {
  pattern: Pattern
  onClose: () => void
  onSaved: () => void
}) {
  const { canEdit } = useApp()
  const [rows, setRows] = useState<PatternStop[]>(pattern.stops ?? [])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const stopParams = useMemo(() => ({ location_type: 'stop' }), [])

  // Re-seed when a different pattern is opened. `useState` only reads its
  // initial value once, so without this the editor would keep showing the
  // first pattern's stops.
  useEffect(() => {
    setRows(pattern.stops ?? [])
    setSaved(false)
    setError('')
  }, [pattern.id, pattern.stops])

  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= rows.length) return
    const next = [...rows]
    ;[next[index], next[target]] = [next[target], next[index]]
    setRows(next)
  }

  function update(index: number, patch: Partial<PatternStop>) {
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  async function save() {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      // The response is the saved pattern, so local state is replaced with
      // what the server actually stored rather than what we hoped it would.
      const updated = await api.put<Pattern>(`/patterns/${pattern.id}/stops`, {
        stops: rows.map((row, index) => ({
          location_id: row.location_id,
          sequence: index + 1,
          is_timepoint: !!row.is_timepoint,
          default_run_seconds: Number(row.default_run_seconds) || 0,
          default_dwell_seconds: Number(row.default_dwell_seconds) || 0,
          distance_from_start_m:
            row.distance_from_start_m === null || row.distance_from_start_m === undefined
              ? null
              : Number(row.distance_from_start_m),
          pickup_type: row.pickup_type || 'regular',
          drop_off_type: row.drop_off_type || 'regular',
        })),
      })
      setRows(updated.stops ?? [])
      setSaved(true)
      // Tell the pattern table its stop_count is now out of date.
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  // The pattern payload already carries each stop's name and coordinates, so
  // the editor needs no separate copy of the locations table.
  const mapPoints = rows
    .filter((row) => row.lat != null && row.lon != null)
    .map((row) => ({
      id: row.location_id,
      name: row.location_name ?? `#${row.location_id}`,
      lat: row.lat as number,
      lon: row.lon as number,
      kind: 'stop',
    }))

  return (
    <Modal
      wide
      title={`Stops — ${pattern.name}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          {canEdit && (
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save stop list'}
            </button>
          )}
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      {saved && <Alert kind="ok">Stop list saved.</Alert>}
      <p className="small muted" style={{ marginTop: 0 }}>
        The whole list is saved at once and renumbered 1…n. "Run" is the time
        from the previous stop; "dwell" is time spent at this one. Those two
        values are what a generated timetable is laid out from.
        {' '}
        A pattern that already has trips cannot have its stops changed — copy
        it instead, so existing stop times stay valid.
      </p>

      <div className="cols side">
        <div>
          {rows.length === 0 ? (
            <Empty>No stops yet. Add one below.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Stop</th>
                    <th className="num">Run (s)</th>
                    <th className="num">Dwell (s)</th>
                    <th>Timepoint</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      <td className="num">{index + 1}</td>
                      <td>{row.location_name ?? `#${row.location_id}`}</td>
                      <td className="num">
                        <input
                          type="number"
                          style={{ width: 80 }}
                          disabled={index === 0}
                          title={index === 0 ? 'The trip starts here' : ''}
                          value={index === 0 ? 0 : (row.default_run_seconds ?? 0)}
                          onChange={(e) => update(index, { default_run_seconds: Number(e.target.value) })}
                        />
                      </td>
                      <td className="num">
                        <input
                          type="number"
                          style={{ width: 80 }}
                          value={row.default_dwell_seconds ?? 0}
                          onChange={(e) => update(index, { default_dwell_seconds: Number(e.target.value) })}
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          style={{ width: 'auto' }}
                          checked={!!row.is_timepoint}
                          onChange={(e) => update(index, { is_timepoint: e.target.checked })}
                        />
                      </td>
                      <td className="actions nowrap">
                        <button className="small" onClick={() => move(index, -1)} disabled={index === 0}>
                          ↑
                        </button>{' '}
                        <button
                          className="small"
                          onClick={() => move(index, 1)}
                          disabled={index === rows.length - 1}
                        >
                          ↓
                        </button>{' '}
                        <button
                          className="small danger"
                          onClick={() => setRows(rows.filter((_, i) => i !== index))}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {canEdit && (
            <div className="toolbar" style={{ marginTop: 10 }}>
              <div style={{ minWidth: 280 }}>
                <Field label="Add a stop">
                  <EntitySelect
                    endpoint="/locations"
                    params={stopParams}
                    value={null}
                    allowClear={false}
                    placeholder="Search stops…"
                    sublabelOf={(row) => row.code}
                    onChange={async (id) => {
                      if (id == null) return
                      let name = `#${id}`
                      let lat: number | null = null
                      let lon: number | null = null
                      try {
                        const row = await api.get<Location>(`/locations/${id}`)
                        name = row.name
                        lat = row.lat
                        lon = row.lon
                      } catch {
                        /* fall back to the id */
                      }
                      setRows((current) => [
                        ...current,
                        {
                          sequence: current.length + 1,
                          location_id: id,
                          location_name: name,
                          lat,
                          lon,
                          is_timepoint: false,
                          default_run_seconds: current.length === 0 ? 0 : 240,
                          default_dwell_seconds: 0,
                          distance_from_start_m: null,
                          pickup_type: 'regular',
                          drop_off_type: 'regular',
                        },
                      ])
                    }}
                  />
                </Field>
              </div>
              <span className="muted small" style={{ marginTop: 16 }}>
                Only stop-type locations are searched — a pattern cannot call at a depot.
              </span>
            </div>
          )}
        </div>

        <div>
          {mapPoints.length > 0 ? (
            <MapView points={mapPoints} path={mapPoints} small />
          ) : (
            <Empty>Add stops with coordinates to see the route.</Empty>
          )}
        </div>
      </div>
    </Modal>
  )
}
