import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  Calendar,
  Line,
  Pattern,
  ScheduleVersion,
  Timetable,
  Trip,
  TripCall,
} from '../api/types'
import { Pager, useList } from '../components/Crud'
import { EntitySelect } from '../components/EntitySelect'
import {
  Alert,
  Empty,
  Field,
  Modal,
  PageHead,
  Panel,
  Spinner,
  TimeInput,
  secondsToHhmm,
} from '../components/ui'
import { useApp } from '../state/AppContext'

export default function SchedulePage() {
  const { canEdit } = useApp()
  const { items: boards } = useList<ScheduleVersion>('/schedule-versions')
  // Only needed to preselect something sensible; the picker below searches
  // the server rather than reading this list.
  const firstLineParams = useMemo(() => ({ limit: 1 }), [])
  const { items: lines } = useList<Line>('/lines', firstLineParams)

  const [boardId, setBoardId] = useState<string>('')
  const [lineId, setLineId] = useState<string>('')
  const [patternId, setPatternId] = useState<string>('')
  const [calendarId, setCalendarId] = useState<string>('')
  const [timepointsOnly, setTimepointsOnly] = useState(false)

  const { items: patterns } = useList<Pattern>('/patterns', { line_id: lineId }, !!lineId)
  const { items: calendars } = useList<Calendar>(
    '/calendars',
    { schedule_version_id: boardId },
    !!boardId,
  )

  // Preselect the first sensible option at each level so the page is useful
  // immediately rather than after four dropdowns.
  useEffect(() => {
    if (!boardId && boards.length) {
      setBoardId(String((boards.find((b) => b.status === 'active') ?? boards[0]).id))
    }
  }, [boards, boardId])
  useEffect(() => {
    if (!lineId && lines.length) setLineId(String(lines[0].id))
  }, [lines, lineId])
  useEffect(() => {
    if (patterns.length && !patterns.some((p) => String(p.id) === patternId)) {
      setPatternId(String(patterns[0].id))
    }
  }, [patterns, patternId])

  const [timetable, setTimetable] = useState<Timetable | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [generateOpen, setGenerateOpen] = useState(false)
  const [editingTrip, setEditingTrip] = useState<number | null>(null)
  const [selectedTrips, setSelectedTrips] = useState<number[]>([])
  // Trip columns are paged. A high-frequency urban pattern runs 250+ trips a
  // day, and one table that wide is unreadable as well as slow.
  const [columnLimit, setColumnLimit] = useState(40)
  const [columnOffset, setColumnOffset] = useState(0)

  async function load() {
    if (!boardId || !patternId) {
      setTimetable(null)
      return
    }
    setLoading(true)
    setError('')
    try {
      setTimetable(
        await api.get<Timetable>('/timetables', {
          schedule_version_id: boardId,
          pattern_id: patternId,
          calendar_id: calendarId || undefined,
          timepoints_only: timepointsOnly,
          limit: columnLimit,
          offset: columnOffset,
        }),
      )
      setSelectedTrips([])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setTimetable(null)
    } finally {
      setLoading(false)
    }
  }

  // Changing what is shown must reset to the first page of columns.
  useEffect(() => {
    setColumnOffset(0)
  }, [boardId, patternId, calendarId])

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardId, patternId, calendarId, timepointsOnly, columnLimit, columnOffset])

  async function deleteSelected() {
    if (!selectedTrips.length) return
    if (!window.confirm(`Delete ${selectedTrips.length} trip(s)? This cannot be undone.`)) return
    try {
      await api.post('/trips/bulk-delete', selectedTrips)
      await load()
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : String(e))
    }
  }

  const pattern = patterns.find((p) => String(p.id) === patternId)

  return (
    <>
      <PageHead
        title="Timetables"
        intro="Trips laid out as stops down, departures across — the same grid the printed timetable is built from."
        actions={
          <>
            <button
              disabled={!timetable}
              title="Every stop, with timepoints in bold"
              onClick={() =>
                api.openBlob('/pdf/timetable', {
                  schedule_version_id: boardId,
                  pattern_id: patternId,
                  calendar_id: calendarId || undefined,
                  timepoints_only: false,
                })
              }
            >
              PDF timetable
            </button>
            <button
              disabled={!boardId}
              onClick={() =>
                api.downloadBlob('/csv/stop-times', `stop_times_board_${boardId}.csv`, {
                  schedule_version_id: boardId,
                })
              }
            >
              CSV export
            </button>
            {canEdit && (
              <button className="primary" disabled={!patternId} onClick={() => setGenerateOpen(true)}>
                Generate trips
              </button>
            )}
          </>
        }
      />

      <Panel>
        <div className="toolbar">
          <Field label="Board">
            <select value={boardId} onChange={(e) => setBoardId(e.target.value)}>
              <option value="">— choose —</option>
              {boards.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.status})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Line">
            <EntitySelect
              endpoint="/lines"
              value={lineId ? Number(lineId) : null}
              onChange={(id) => {
                setLineId(id ? String(id) : '')
                setPatternId('')
              }}
              labelOf={(row) => `${row.short_name}${row.long_name ? ` — ${row.long_name}` : ''}`}
              placeholder="Search lines…"
            />
          </Field>
          <Field label="Pattern">
            <select value={patternId} onChange={(e) => setPatternId(e.target.value)}>
              <option value="">— choose —</option>
              {patterns.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} (dir {p.direction})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Calendar">
            <select value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>
              <option value="">All calendars</option>
              {calendars.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="field inline" style={{ marginTop: 14 }}>
            <input
              type="checkbox"
              checked={timepointsOnly}
              onChange={(e) => setTimepointsOnly(e.target.checked)}
            />
            <label>Timepoints only</label>
          </div>
        </div>
      </Panel>

      <Alert kind="err">{error}</Alert>

      <Panel
        title={
          timetable
            ? `${timetable.line_short_name} — ${timetable.pattern_name}`
            : 'Timetable'
        }
        hint={
          timetable
            ? `${timetable.total_trips.toLocaleString()} trips on this pattern`
            : undefined
        }
        actions={
          canEdit && selectedTrips.length > 0 ? (
            <button className="danger small" onClick={deleteSelected}>
              Delete {selectedTrips.length} selected
            </button>
          ) : null
        }
      >
        {loading ? (
          <Spinner />
        ) : !timetable ? (
          <Empty>Choose a board and a pattern.</Empty>
        ) : timetable.rows.length === 0 ? (
          <Empty>This pattern has no stops yet.</Empty>
        ) : timetable.trip_ids.length === 0 ? (
          <Empty>
            No trips on this pattern for the selected board
            {calendarId ? ' and calendar' : ''}. Use “Generate trips”.
          </Empty>
        ) : (
          <div className="timetable">
            <table>
              <thead>
                <tr>
                  <th className="stopname">Stop</th>
                  {timetable.trip_ids.map((tripId) => (
                    <th key={tripId} style={{ textAlign: 'right' }}>
                      <label
                        className="small"
                        style={{ cursor: 'pointer', margin: 0, color: 'var(--muted)' }}
                        title={`Trip ${tripId}`}
                      >
                        <input
                          type="checkbox"
                          style={{ width: 'auto', marginRight: 3 }}
                          checked={selectedTrips.includes(tripId)}
                          onChange={(e) =>
                            setSelectedTrips((current) =>
                              e.target.checked
                                ? [...current, tripId]
                                : current.filter((id) => id !== tripId),
                            )
                          }
                        />
                        <span
                          onClick={(e) => {
                            e.preventDefault()
                            setEditingTrip(tripId)
                          }}
                        >
                          #{tripId}
                        </span>
                      </label>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {timetable.rows.map((row) => (
                  <tr key={row.pattern_stop_id} className={row.is_timepoint ? 'timepoint' : ''}>
                    <td className="stopname" title={row.location_name}>
                      {row.location_name}
                    </td>
                    {row.cells.map((cell, index) => (
                      <td
                        key={index}
                        className={cell.departure_seconds ? 'time' : 'blank'}
                      >
                        {cell.departure_seconds ? secondsToHhmm(cell.departure_seconds) : '·'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {timetable && timetable.total_trips > 0 && (
          <Pager
            offset={timetable.offset}
            limit={columnLimit}
            total={timetable.total_trips}
            loading={loading}
            onOffset={setColumnOffset}
            onLimit={setColumnLimit}
          />
        )}
      </Panel>

      {generateOpen && pattern && (
        <GenerateTripsModal
          boardId={Number(boardId)}
          pattern={pattern}
          calendars={calendars}
          onClose={() => setGenerateOpen(false)}
          onDone={() => {
            setGenerateOpen(false)
            load()
          }}
        />
      )}

      {editingTrip && (
        <TripEditor tripId={editingTrip} onClose={() => setEditingTrip(null)} onSaved={load} />
      )}
    </>
  )
}

function GenerateTripsModal({
  boardId,
  pattern,
  calendars,
  onClose,
  onDone,
}: {
  boardId: number
  pattern: Pattern
  calendars: Calendar[]
  onClose: () => void
  onDone: () => void
}) {
  const [calendarId, setCalendarId] = useState(calendars[0] ? String(calendars[0].id) : '')
  const [first, setFirst] = useState('06:00')
  const [last, setLast] = useState('09:00')
  const [headway, setHeadway] = useState(30)
  const [headsign, setHeadsign] = useState(pattern.headsign ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError('')
    try {
      const result = await api.post<{ count: number }>('/trips/generate', {
        schedule_version_id: boardId,
        pattern_id: pattern.id,
        calendar_id: Number(calendarId),
        first_departure: first,
        last_departure: last,
        headway_minutes: Number(headway),
        headsign: headsign || null,
      })
      window.alert(`Created ${result.count} trips.`)
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const estimate =
    headway > 0 ? Math.floor((toSeconds(last) - toSeconds(first)) / (headway * 60)) + 1 : 0

  return (
    <Modal
      title={`Generate trips — ${pattern.name}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={run} disabled={busy || !calendarId}>
            {busy ? 'Generating…' : `Create ${estimate > 0 ? estimate : ''} trips`}
          </button>
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      <p className="small muted" style={{ marginTop: 0 }}>
        Each trip's stop times are laid out from the pattern's default run and
        dwell values, then stay editable individually. Times past midnight use
        the service-day clock — 25:10 is 01:10 on the following morning.
      </p>
      <div className="form-grid">
        <Field label="Calendar">
          <select value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>
            <option value="">— choose —</option>
            {calendars.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Headsign">
          <input value={headsign} onChange={(e) => setHeadsign(e.target.value)} />
        </Field>
        <Field label="First departure">
          <TimeInput value={first} onChange={setFirst} />
        </Field>
        <Field label="Last departure">
          <TimeInput value={last} onChange={setLast} />
        </Field>
        <Field label="Headway (minutes)">
          <input type="number" min={1} value={headway} onChange={(e) => setHeadway(Number(e.target.value))} />
        </Field>
      </div>
    </Modal>
  )
}

function toSeconds(value: string): number {
  const [h, m, s] = value.split(':').map(Number)
  return (h || 0) * 3600 + (m || 0) * 60 + (s || 0)
}

function fromSeconds(total: number): string {
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

/** Halfway between two service-day times, for re-timing a restored stop. */
function midpoint(a: string | null, b: string | null): string {
  if (!a || !b) return a ?? b ?? '00:00:00'
  return fromSeconds(Math.round((toSeconds(a) + toSeconds(b)) / 2))
}

function TripEditor({
  tripId,
  onClose,
  onSaved,
}: {
  tripId: number
  onClose: () => void
  onSaved: () => void
}) {
  const { canEdit } = useApp()
  const [trip, setTrip] = useState<Trip | null>(null)
  const [error, setError] = useState('')
  const [shift, setShift] = useState(0)
  const [calls, setCalls] = useState<TripCall[]>([])

  useEffect(() => {
    api
      .get<Trip>(`/trips/${tripId}/detail`)
      .then((t) => {
        setTrip(t)
        setCalls(t.calls ?? [])
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)))
  }, [tripId])

  function update(patternStopId: number, patch: Partial<TripCall>) {
    setCalls((current) =>
      current.map((call) =>
        call.pattern_stop_id === patternStopId ? { ...call, ...patch } : call,
      ),
    )
  }

  /**
   * Clearing a time skips the stop: the trip runs past without calling.
   * That is stored as the absence of a stop time, not as a blank one, so
   * exports and the itinerary search treat it correctly rather than seeing
   * a call at 00:00.
   */
  function setTime(call: TripCall, field: 'arrival_seconds' | 'departure_seconds', value: string) {
    const cleared = !value.trim()
    if (cleared) {
      const other =
        field === 'arrival_seconds' ? call.departure_seconds : call.arrival_seconds
      // Clearing either box skips the stop; clearing one when the other is
      // already blank is the same thing, so both routes converge here.
      update(call.pattern_stop_id, {
        skipped: true,
        arrival_seconds: null,
        departure_seconds: null,
      })
      void other
      return
    }
    const patch: Partial<TripCall> = { [field]: value, skipped: false }
    // Filling one box on a skipped stop revives it; mirror the value into
    // the empty twin so the row is immediately valid.
    if (call.skipped) {
      patch.arrival_seconds = value
      patch.departure_seconds = value
    }
    update(call.pattern_stop_id, patch)
  }

  function restore(call: TripCall) {
    // Re-time a revived stop between its neighbours so it lands somewhere
    // sensible instead of at midnight.
    const index = calls.findIndex((c) => c.pattern_stop_id === call.pattern_stop_id)
    const before = [...calls.slice(0, index)].reverse().find((c) => !c.skipped)
    const after = calls.slice(index + 1).find((c) => !c.skipped)
    const guess =
      before && after
        ? midpoint(before.departure_seconds, after.arrival_seconds)
        : before?.departure_seconds ?? after?.arrival_seconds ?? '00:00:00'
    update(call.pattern_stop_id, {
      skipped: false,
      arrival_seconds: guess,
      departure_seconds: guess,
    })
  }

  async function save() {
    setError('')
    try {
      await api.patch(`/trips/${tripId}`, {
        // Skipped stops are simply not sent.
        stop_times: calls
          .filter((call) => !call.skipped)
          .map((call) => ({
            pattern_stop_id: call.pattern_stop_id,
            arrival_seconds: call.arrival_seconds,
            departure_seconds: call.departure_seconds,
            is_timepoint: call.is_timepoint,
            pickup_type: call.pickup_type,
            drop_off_type: call.drop_off_type,
          })),
      })
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  const servedCount = calls.filter((c) => !c.skipped).length

  async function applyShift() {
    setError('')
    try {
      await api.patch(`/trips/${tripId}`, { shift_seconds: Math.round(shift * 60) })
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Modal
      title={`Trip #${tripId}`}
      onClose={onClose}
      footer={
        canEdit ? (
          <>
            <button onClick={onClose}>Cancel</button>
            <button className="primary" onClick={save} disabled={servedCount < 2}>
              Save times
            </button>
          </>
        ) : (
          <button onClick={onClose}>Close</button>
        )
      }
    >
      <Alert kind="err">{error}</Alert>
      {!trip ? (
        <Spinner />
      ) : (
        <>
          <p className="small muted" style={{ marginTop: 0 }}>
            {trip.line_short_name} · {trip.pattern_name} · {trip.calendar_name}
            {trip.block_name && ` · block ${trip.block_name}`}
          </p>

          {canEdit && (
            <div className="toolbar">
              <Field label="Shift whole trip (minutes)">
                <input
                  type="number"
                  value={shift}
                  onChange={(e) => setShift(Number(e.target.value))}
                  style={{ width: 100 }}
                />
              </Field>
              <button style={{ marginTop: 14 }} onClick={applyShift} disabled={!shift}>
                Apply shift
              </button>
              <span className="muted small" style={{ marginTop: 18 }}>
                Moves every call, keeping the running times intact.
              </span>
            </div>
          )}

          <p className="small muted">
            Clear a stop's times to <strong>skip</strong> it — the trip runs
            past without calling, which is how a limited-stop or short working
            is built without cloning the pattern. Skipped stops show as “·” in
            the grid and are left out of exports. Type a time back in to
            restore the call.
          </p>

          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Stop</th>
                  <th>Arrival</th>
                  <th>Departure</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr
                    key={call.pattern_stop_id}
                    style={call.skipped ? { opacity: 0.55 } : undefined}
                  >
                    <td className="num">{call.sequence}</td>
                    <td>
                      {call.location_name}
                      {call.skipped && (
                        <span className="tag grey" style={{ marginLeft: 6 }}>
                          skipped
                        </span>
                      )}
                    </td>
                    <td style={{ width: 120 }}>
                      <TimeInput
                        value={call.skipped ? '' : call.arrival_seconds}
                        placeholder="— skip —"
                        onChange={(v) => setTime(call, 'arrival_seconds', v)}
                      />
                    </td>
                    <td style={{ width: 120 }}>
                      <TimeInput
                        value={call.skipped ? '' : call.departure_seconds}
                        placeholder="— skip —"
                        onChange={(v) => setTime(call, 'departure_seconds', v)}
                      />
                    </td>
                    <td className="actions">
                      {canEdit &&
                        (call.skipped ? (
                          <button className="small" onClick={() => restore(call)}>
                            Call here
                          </button>
                        ) : (
                          <button
                            className="small"
                            title="Skip this stop on this trip"
                            onClick={() =>
                              update(call.pattern_stop_id, {
                                skipped: true,
                                arrival_seconds: null,
                                departure_seconds: null,
                              })
                            }
                          >
                            Skip
                          </button>
                        ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {servedCount < 2 && (
            <Alert kind="err">
              A trip must call at at least two stops; this one calls at{' '}
              {servedCount}.
            </Alert>
          )}
        </>
      )}
    </Modal>
  )
}
