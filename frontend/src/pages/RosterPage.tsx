import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  BlockCoverage,
  Duty,
  DutyPiece,
  DutyPieceType,
  Driver,
  ScheduleVersion,
} from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import { EntitySelect } from '../components/EntitySelect'
import {
  Alert,
  Empty,
  Field,
  IssueList,
  Modal,
  PageHead,
  Panel,
  Spinner,
  TimeInput,
  durationLabel,
  secondsToHhmm,
} from '../components/ui'
import { useApp } from '../state/AppContext'

type Tab = 'roster' | 'drivers'

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export default function RosterPage() {
  const [tab, setTab] = useState<Tab>('roster')

  return (
    <>
      <PageHead
        title="Roster"
        intro="Build duties from finished blocks: assign whole blocks or parts of them, insert breaks, and check the result against the operating parameters."
      />
      <div className="toolbar">
        <button className={tab === 'roster' ? 'primary' : ''} onClick={() => setTab('roster')}>
          Duties
        </button>
        <button className={tab === 'drivers' ? 'primary' : ''} onClick={() => setTab('drivers')}>
          Drivers
        </button>
      </div>

      {tab === 'roster' ? <RosterTab /> : <DriversTab />}
    </>
  )
}

/* ----------------------------------------------------------------- roster */

function RosterTab() {
  const { canEdit } = useApp()
  const { items: boards } = useList<ScheduleVersion>('/schedule-versions')
  const [boardId, setBoardId] = useState('')
  const [date, setDate] = useState(todayIso())
  const [duties, setDuties] = useState<Duty[]>([])
  const [coverage, setCoverage] = useState<BlockCoverage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Duty | null>(null)
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    if (!boardId && boards.length) {
      setBoardId(String((boards.find((b) => b.status === 'active') ?? boards[0]).id))
    }
  }, [boards, boardId])

  const load = useCallback(async () => {
    if (!boardId || !date) {
      setDuties([])
      setCoverage([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const [dutyRows, coverageRows] = await Promise.all([
        api.get<Duty[]>('/duties', { schedule_version_id: boardId, date }),
        api.get<BlockCoverage[]>('/duties/coverage/report', {
          schedule_version_id: boardId,
          date,
        }),
      ])
      setDuties(dutyRows)
      setCoverage(coverageRows)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [boardId, date])

  useEffect(() => {
    load()
  }, [load])

  const uncovered = coverage.filter((c) => !c.fully_covered)

  return (
    <>
      <Panel>
        <div className="toolbar">
          <Field label="Schedule board">
            <select value={boardId} onChange={(e) => setBoardId(e.target.value)}>
              <option value="">— choose —</option>
              {boards.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.status})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <span className="spacer" />
          {canEdit && boardId && (
            <button className="primary" style={{ marginTop: 14 }} onClick={() => setCreating(true)}>
              New duty
            </button>
          )}
        </div>
      </Panel>

      <Alert kind="err">{error}</Alert>

      <div className="cols side">
        <Panel title="Duties" hint={`${duties.length} on this date`}>
          {loading ? (
            <Spinner />
          ) : !boardId ? (
            <Empty>Choose a schedule board.</Empty>
          ) : duties.length === 0 ? (
            <Empty>No duties built for this date yet.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Duty</th>
                    <th>Driver</th>
                    <th>Sign on</th>
                    <th>Sign off</th>
                    <th className="num">Spread</th>
                    <th className="num">Driving</th>
                    <th className="num">Break</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {duties.map((duty) => (
                    <tr key={duty.id}>
                      <td>
                        <strong>{duty.name}</strong>
                      </td>
                      <td>
                        {duty.driver_name ?? <span className="tag warn">unassigned</span>}
                      </td>
                      <td className="nowrap">{secondsToHhmm(duty.start_seconds)}</td>
                      <td className="nowrap">{secondsToHhmm(duty.end_seconds)}</td>
                      <td className="num nowrap">{minutesLabel(duty.working_minutes)}</td>
                      <td className="num nowrap">{minutesLabel(duty.driving_minutes)}</td>
                      <td className="num nowrap">{duty.break_minutes}m</td>
                      <td className="actions nowrap">
                        <button className="small" onClick={() => setEditing(duty)}>
                          Build
                        </button>{' '}
                        <button
                          className="small"
                          title="Printable duty card"
                          onClick={() => api.openBlob('/pdf/duty-card', { duty_id: duty.id })}
                        >
                          Card
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <Panel
          title="Block coverage"
          hint={uncovered.length ? `${uncovered.length} incomplete` : 'all covered'}
        >
          <p className="small muted" style={{ marginTop: 0 }}>
            Which pieces of each block still have nobody driving them on this
            date. A block split between two drivers shows as covered only once
            both halves are rostered.
          </p>
          {coverage.length === 0 ? (
            <Empty>No blocks on this board.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Block</th>
                    <th className="num">Covered</th>
                    <th>Missing pieces</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.map((row) => (
                    <tr key={row.block_id}>
                      <td>{row.block_name}</td>
                      <td className="num">
                        {row.covered_sequences.length}/{row.total_pieces}
                      </td>
                      <td>
                        {row.fully_covered ? (
                          <span className="tag ok">complete</span>
                        ) : (
                          <span className="tag warn">
                            {summariseRanges(row.uncovered_sequences)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      {creating && (
        <NewDutyModal
          boardId={Number(boardId)}
          date={date}
          onClose={() => setCreating(false)}
          onCreated={(duty) => {
            setCreating(false)
            load()
            setEditing(duty)
          }}
        />
      )}

      {editing && (
        <DutyBuilder
          duty={editing}
          onClose={() => {
            setEditing(null)
            load()
          }}
        />
      )}
    </>
  )
}

function minutesLabel(total: number): string {
  if (!total) return '—'
  const hours = Math.floor(total / 60)
  return hours ? `${hours}h ${total % 60}m` : `${total}m`
}

/** "1–3, 7" reads better than "1, 2, 3, 7" once a block gets long. */
function summariseRanges(values: number[]): string {
  if (values.length === 0) return '—'
  const parts: string[] = []
  let start = values[0]
  let previous = values[0]
  for (const value of values.slice(1)) {
    if (value === previous + 1) {
      previous = value
      continue
    }
    parts.push(start === previous ? `${start}` : `${start}–${previous}`)
    start = value
    previous = value
  }
  parts.push(start === previous ? `${start}` : `${start}–${previous}`)
  return parts.join(', ')
}

function NewDutyModal({
  boardId,
  date,
  onClose,
  onCreated,
}: {
  boardId: number
  date: string
  onClose: () => void
  onCreated: (duty: Duty) => void
}) {
  const [name, setName] = useState('')
  const [driverId, setDriverId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function create() {
    setBusy(true)
    setError('')
    try {
      const duty = await api.post<Duty>('/duties', {
        name,
        date,
        schedule_version_id: boardId,
        driver_id: driverId,
        pieces: [],
      })
      onCreated(duty)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="New duty"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={create} disabled={busy || !name.trim()}>
            {busy ? 'Creating…' : 'Create and build'}
          </button>
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      <Field label="Duty name" hint="unique for this board and date">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. 101/1" />
      </Field>
      <Field label="Driver" hint="optional — duties are often built before they are assigned">
        <EntitySelect
          endpoint="/drivers"
          params={{ is_active: true }}
          value={driverId}
          onChange={setDriverId}
          labelOf={(row) => `${row.code} — ${row.display_name}`}
          placeholder="Leave unassigned"
        />
      </Field>
    </Modal>
  )
}

/* ----------------------------------------------------------- duty builder */

const PIECE_LABELS: Record<DutyPieceType, string> = {
  sign_on: 'Sign on',
  block_segment: 'Drive block',
  break: 'Break',
  sign_off: 'Sign off',
}

function DutyBuilder({ duty, onClose }: { duty: Duty; onClose: () => void }) {
  const { canEdit } = useApp()
  const [detail, setDetail] = useState<Duty | null>(null)
  const [pieces, setPieces] = useState<DutyPiece[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)

  const blockParams = useMemo(
    () => ({ schedule_version_id: duty.schedule_version_id }),
    [duty.schedule_version_id],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.get<Duty>(`/duties/${duty.id}`)
      setDetail(data)
      setPieces(data.pieces ?? [])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [duty.id])

  useEffect(() => {
    load()
  }, [load])

  function update(index: number, patch: Partial<DutyPiece>) {
    setPieces(pieces.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= pieces.length) return
    const next = [...pieces]
    ;[next[index], next[target]] = [next[target], next[index]]
    setPieces(next)
  }

  function add(type: DutyPieceType) {
    setPieces([
      ...pieces,
      {
        sequence: pieces.length + 1,
        piece_type: type,
        block_id: null,
        from_block_piece_sequence: null,
        to_block_piece_sequence: null,
        location_id: null,
        start_seconds: type === 'block_segment' ? null : '00:00',
        end_seconds: type === 'block_segment' ? null : '00:00',
        notes: null,
      },
    ])
  }

  async function save() {
    setSaving(true)
    setError('')
    try {
      const data = await api.put<Duty>(`/duties/${duty.id}/pieces`, {
        pieces: pieces.map((piece, index) => ({
          sequence: index + 1,
          piece_type: piece.piece_type,
          block_id: piece.piece_type === 'block_segment' ? piece.block_id : null,
          from_block_piece_sequence:
            piece.piece_type === 'block_segment' ? piece.from_block_piece_sequence : null,
          to_block_piece_sequence:
            piece.piece_type === 'block_segment' ? piece.to_block_piece_sequence : null,
          location_id: piece.piece_type === 'block_segment' ? null : piece.location_id,
          start_seconds: piece.piece_type === 'block_segment' ? null : piece.start_seconds,
          end_seconds: piece.piece_type === 'block_segment' ? null : piece.end_seconds,
          notes: piece.notes,
        })),
      })
      setDetail(data)
      setPieces(data.pieces ?? [])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      wide
      title={`Duty ${duty.name} — ${duty.date}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={() => api.openBlob('/pdf/duty-card', { duty_id: duty.id })}>
            Duty card PDF
          </button>
          <span style={{ flex: 1 }} />
          <button onClick={onClose}>Close</button>
          {canEdit && (
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save duty'}
            </button>
          )}
        </>
      }
    >
      <Alert kind="err">{error}</Alert>

      {loading ? (
        <Spinner />
      ) : (
        <>
          {detail && (
            <div className="toolbar">
              <span className="tag">
                Driver: {detail.driver_name ?? 'unassigned'}
              </span>
              <span className="tag grey">
                {secondsToHhmm(detail.start_seconds) || '—'} →{' '}
                {secondsToHhmm(detail.end_seconds) || '—'}
              </span>
              <span className="tag grey">Spread {minutesLabel(detail.working_minutes)}</span>
              <span className="tag grey">Driving {minutesLabel(detail.driving_minutes)}</span>
              <span className={`tag ${detail.break_minutes ? 'ok' : 'warn'}`}>
                Break {detail.break_minutes}m
              </span>
              <span className="spacer" />
              <div style={{ minWidth: 220 }}>
                <EntitySelect
                  endpoint="/drivers"
                  params={{ is_active: true }}
                  value={detail.driver_id}
                  labelOf={(row) => `${row.code} — ${row.display_name}`}
                  placeholder="Assign a driver…"
                  onChange={async (id) => {
                    try {
                      const updated = await api.patch<Duty>(`/duties/${duty.id}`, {
                        driver_id: id,
                      })
                      setDetail(updated)
                    } catch (e) {
                      setError(e instanceof ApiError ? e.message : String(e))
                    }
                  }}
                />
              </div>
            </div>
          )}

          <p className="small muted" style={{ marginTop: 0 }}>
            A "drive block" piece takes its times from the block itself — leave
            the range blank to take the whole block, or set a piece range to
            split it with another driver. Breaks and sign on/off carry their
            own times and a location.
          </p>

          {pieces.length === 0 ? (
            <Empty>No pieces yet. Add a sign-on to start.</Empty>
          ) : (
            <div className="table-wrap allow-overflow">
              <table className="grid">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Type</th>
                    <th>Block / location</th>
                    <th>Range</th>
                    <th>Start</th>
                    <th>End</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pieces.map((piece, index) => {
                    const isSegment = piece.piece_type === 'block_segment'
                    return (
                      <tr key={index}>
                        <td className="num">{index + 1}</td>
                        <td className="nowrap">
                          <span className={`tag ${piece.piece_type === 'break' ? 'warn' : ''}`}>
                            {PIECE_LABELS[piece.piece_type]}
                          </span>
                        </td>
                        <td style={{ minWidth: 190 }}>
                          {isSegment ? (
                            <EntitySelect
                              endpoint="/blocks"
                              params={blockParams}
                              value={piece.block_id}
                              onChange={(v) => update(index, { block_id: v })}
                              disabled={!canEdit}
                              placeholder="Search blocks…"
                            />
                          ) : (
                            <EntitySelect
                              endpoint="/locations"
                              value={piece.location_id}
                              onChange={(v) => update(index, { location_id: v })}
                              disabled={!canEdit}
                              placeholder="Where…"
                              sublabelOf={(row) => row.location_type}
                            />
                          )}
                        </td>
                        <td className="nowrap">
                          {isSegment ? (
                            <>
                              <input
                                type="number"
                                min={1}
                                style={{ width: 58, display: 'inline-block' }}
                                placeholder="all"
                                disabled={!canEdit}
                                value={piece.from_block_piece_sequence ?? ''}
                                onChange={(e) =>
                                  update(index, {
                                    from_block_piece_sequence: e.target.value
                                      ? Number(e.target.value)
                                      : null,
                                  })
                                }
                              />
                              {' – '}
                              <input
                                type="number"
                                min={1}
                                style={{ width: 58, display: 'inline-block' }}
                                placeholder="all"
                                disabled={!canEdit}
                                value={piece.to_block_piece_sequence ?? ''}
                                onChange={(e) =>
                                  update(index, {
                                    to_block_piece_sequence: e.target.value
                                      ? Number(e.target.value)
                                      : null,
                                  })
                                }
                              />
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td style={{ width: 100 }}>
                          {isSegment ? (
                            <span className="small nowrap">
                              {secondsToHhmm(piece.effective_start_seconds) || '—'}
                            </span>
                          ) : (
                            <TimeInput
                              value={piece.start_seconds}
                              onChange={(v) => update(index, { start_seconds: v || null })}
                            />
                          )}
                        </td>
                        <td style={{ width: 100 }}>
                          {isSegment ? (
                            <span className="small nowrap">
                              {secondsToHhmm(piece.effective_end_seconds) || '—'}
                              {piece.effective_start_seconds && (
                                <span className="muted">
                                  {' '}
                                  ({durationLabel(
                                    piece.effective_start_seconds,
                                    piece.effective_end_seconds,
                                  )})
                                </span>
                              )}
                            </span>
                          ) : (
                            <TimeInput
                              value={piece.end_seconds}
                              onChange={(v) => update(index, { end_seconds: v || null })}
                            />
                          )}
                        </td>
                        <td className="actions nowrap">
                          {canEdit && (
                            <>
                              <button
                                className="small"
                                onClick={() => move(index, -1)}
                                disabled={index === 0}
                              >
                                ↑
                              </button>{' '}
                              <button
                                className="small"
                                onClick={() => move(index, 1)}
                                disabled={index === pieces.length - 1}
                              >
                                ↓
                              </button>{' '}
                              <button
                                className="small danger"
                                onClick={() => setPieces(pieces.filter((_, i) => i !== index))}
                              >
                                ✕
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {canEdit && (
            <div className="toolbar" style={{ marginTop: 10 }}>
              <button onClick={() => add('sign_on')}>+ Sign on</button>
              <button onClick={() => add('block_segment')}>+ Drive block</button>
              <button onClick={() => add('break')}>+ Break</button>
              <button onClick={() => add('sign_off')}>+ Sign off</button>
              <span className="muted small">
                Block times appear once you save — they come from the block.
              </span>
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <h3 style={{ fontSize: 14 }}>Rule check</h3>
            <p className="small muted" style={{ marginTop: 0 }}>
              Checked against the values on the Settings page. Violations are
              flagged but never block saving, so an edge case can be accepted
              deliberately.
            </p>
            <IssueList report={detail?.validation ?? null} />
          </div>
        </>
      )}
    </Modal>
  )
}

/* ---------------------------------------------------------------- drivers */

function DriversTab() {
  return (
    <Panel>
      <CrudTable<Driver>
        endpoint="/drivers"
        entityName="Driver"
        columns={[
          { key: 'code', label: 'Code', sortKey: 'code' },
          { key: 'display_name', label: 'Name', sortKey: 'last_name' },
          { key: 'base_location_name', label: 'Base' },
          { key: 'phone', label: 'Phone' },
          { key: 'email', label: 'Email' },
          {
            key: 'is_active',
            label: 'Status',
            sortKey: 'is_active',
            render: (row) =>
              row.is_active ? (
                <span className="tag ok">active</span>
              ) : (
                <span className="tag grey">inactive</span>
              ),
          },
        ]}
        fields={[
          { name: 'code', label: 'Staff code', required: true },
          { name: 'first_name', label: 'First name', required: true },
          { name: 'last_name', label: 'Last name', required: true },
          {
            name: 'base_location_id',
            label: 'Base depot',
            type: 'entity',
            endpoint: '/locations',
            entityParams: { location_type: 'depot' },
          },
          { name: 'phone', label: 'Phone' },
          { name: 'email', label: 'Email' },
          { name: 'is_active', label: 'Active', type: 'checkbox' },
          { name: 'notes', label: 'Notes', type: 'textarea' },
        ]}
        defaults={{ is_active: true }}
      />
    </Panel>
  )
}
