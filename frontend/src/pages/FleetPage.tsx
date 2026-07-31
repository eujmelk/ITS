import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  Block,
  BlockPiece,
  BlockPieceType,
  Location,
  ScheduleVersion,
  UnassignedTrip,
  ValidationReport,
  Vehicle,
  VehicleType,
} from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import type { Column } from '../components/Crud'
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

type Tab = 'blocks' | 'vehicles' | 'types'

export default function FleetPage() {
  const [tab, setTab] = useState<Tab>('blocks')
  const { items: types, reload: reloadTypes } = useList<VehicleType>('/vehicle-types')
  const { items: locations } = useList<Location>('/locations')

  return (
    <>
      <PageHead
        title="Fleet & blocks"
        intro="A block is a vehicle's whole day: pull-out from the depot, revenue trips, deadheads between them, pull-in at the end. Every leg references a real location, so continuity can actually be checked."
      />

      <div className="toolbar">
        <button className={tab === 'blocks' ? 'primary' : ''} onClick={() => setTab('blocks')}>
          Blocks
        </button>
        <button className={tab === 'vehicles' ? 'primary' : ''} onClick={() => setTab('vehicles')}>
          Vehicles
        </button>
        <button className={tab === 'types' ? 'primary' : ''} onClick={() => setTab('types')}>
          Vehicle types
        </button>
      </div>

      {tab === 'blocks' && <BlocksTab types={types} locations={locations} />}

      {tab === 'vehicles' && (
        <Panel>
          <CrudTable<Vehicle>
            endpoint="/vehicles"
            entityName="Vehicle"
            columns={[
              { key: 'fleet_number', label: 'Fleet no.' },
              { key: 'vehicle_type_name', label: 'Type' },
              { key: 'depot_name', label: 'Home depot' },
              { key: 'registration', label: 'Registration' },
              {
                key: 'is_active',
                label: 'Status',
                render: (row) =>
                  row.is_active ? <span className="tag ok">active</span> : <span className="tag grey">out of service</span>,
              },
            ]}
            fields={[
              { name: 'fleet_number', label: 'Fleet number', required: true },
              {
                name: 'vehicle_type_id',
                label: 'Vehicle type',
                type: 'select',
                required: true,
                options: types.map((t) => ({ value: t.id, label: t.name })),
              },
              {
                name: 'depot_location_id',
                label: 'Home depot',
                type: 'select',
                options: locations
                  .filter((l) => l.location_type === 'depot' || l.location_type === 'garage')
                  .map((l) => ({ value: l.id, label: l.name })),
              },
              { name: 'registration', label: 'Registration' },
              { name: 'is_active', label: 'In service', type: 'checkbox' },
              { name: 'notes', label: 'Notes', type: 'textarea' },
            ]}
            defaults={{ is_active: true }}
          />
        </Panel>
      )}

      {tab === 'types' && (
        <Panel>
          <CrudTable<VehicleType>
            endpoint="/vehicle-types"
            entityName="Vehicle type"
            onChanged={reloadTypes}
            columns={[
              { key: 'name', label: 'Type' },
              { key: 'code', label: 'Code' },
              { key: 'capacity_seated', label: 'Seated', numeric: true },
              { key: 'capacity_standing', label: 'Standing', numeric: true },
              { key: 'fuel_type', label: 'Fuel' },
              { key: 'length_m', label: 'Length (m)', numeric: true },
            ]}
            fields={[
              { name: 'name', label: 'Name', required: true },
              { name: 'code', label: 'Code' },
              { name: 'capacity_seated', label: 'Seated capacity', type: 'number' },
              { name: 'capacity_standing', label: 'Standing capacity', type: 'number' },
              { name: 'fuel_type', label: 'Fuel type' },
              { name: 'length_m', label: 'Length (m)', type: 'number', step: 'any' },
              { name: 'wheelchair_accessible', label: 'Wheelchair accessible', type: 'checkbox' },
              { name: 'notes', label: 'Notes', type: 'textarea' },
            ]}
            defaults={{ wheelchair_accessible: true }}
          />
        </Panel>
      )}
    </>
  )
}

/* ---------------------------------------------------------------- blocks */

function BlocksTab({ types, locations }: { types: VehicleType[]; locations: Location[] }) {
  const { items: boards } = useList<ScheduleVersion>('/schedule-versions')
  const { items: vehicles } = useList<Vehicle>('/vehicles')
  const [boardId, setBoardId] = useState('')
  const [editing, setEditing] = useState<Block | null>(null)
  const [allReport, setAllReport] = useState<ValidationReport | null>(null)

  useEffect(() => {
    if (!boardId && boards.length) {
      setBoardId(String((boards.find((b) => b.status === 'active') ?? boards[0]).id))
    }
  }, [boards, boardId])

  const params = useMemo(
    () => (boardId ? { schedule_version_id: boardId } : undefined),
    [boardId],
  )

  const columns: Column<Block>[] = [
    { key: 'name', label: 'Block' },
    { key: 'vehicle_fleet_number', label: 'Vehicle' },
    { key: 'piece_count', label: 'Pieces', numeric: true },
    {
      key: 'span',
      label: 'Span',
      render: (row) =>
        row.start_seconds ? (
          <span className="nowrap">
            {secondsToHhmm(row.start_seconds)} – {secondsToHhmm(row.end_seconds)}{' '}
            <span className="muted small">({durationLabel(row.start_seconds, row.end_seconds)})</span>
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
  ]

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
          <button
            style={{ marginTop: 14 }}
            disabled={!boardId}
            onClick={async () => {
              try {
                setAllReport(
                  await api.get<ValidationReport>('/fleet/blocks/validate-all', {
                    schedule_version_id: boardId,
                  }),
                )
              } catch (e) {
                window.alert(e instanceof ApiError ? e.message : String(e))
              }
            }}
          >
            Validate all blocks
          </button>
        </div>

        {!boardId ? (
          <Empty>Choose a schedule board.</Empty>
        ) : (
          <CrudTable<Block>
            endpoint="/blocks"
            entityName="Block"
            params={params}
            columns={columns}
            defaults={{ schedule_version_id: Number(boardId) }}
            toPayload={(values, mode) =>
              mode === 'create' ? { ...values, schedule_version_id: Number(boardId) } : values
            }
            fields={[
              { name: 'name', label: 'Block name', required: true, hint: 'unique within the board' },
              {
                name: 'vehicle_id',
                label: 'Vehicle',
                type: 'select',
                options: vehicles.map((v) => ({ value: v.id, label: v.fleet_number })),
              },
              {
                name: 'vehicle_type_id',
                label: 'Required vehicle type',
                type: 'select',
                options: types.map((t) => ({ value: t.id, label: t.name })),
              },
              { name: 'notes', label: 'Notes', type: 'textarea' },
            ]}
            extraRowActions={(row) => (
              <button className="small" onClick={() => setEditing(row)}>
                Pieces ({row.piece_count})
              </button>
            )}
          />
        )}
      </Panel>

      {allReport && (
        <Panel
          title="Block validation"
          actions={
            <button className="small" onClick={() => setAllReport(null)}>
              Dismiss
            </button>
          }
        >
          <IssueList report={allReport} />
        </Panel>
      )}

      {editing && (
        <BlockPiecesEditor
          block={editing}
          locations={locations}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}

const PIECE_TYPES: { value: BlockPieceType; label: string }[] = [
  { value: 'pull_out', label: 'Pull-out (depot → first stop)' },
  { value: 'trip', label: 'Trip (in service)' },
  { value: 'deadhead', label: 'Deadhead (empty)' },
  { value: 'pull_in', label: 'Pull-in (last stop → depot)' },
]

function BlockPiecesEditor({
  block,
  locations,
  onClose,
}: {
  block: Block
  locations: Location[]
  onClose: () => void
}) {
  const { canEdit } = useApp()
  const [pieces, setPieces] = useState<BlockPiece[]>([])
  const [report, setReport] = useState<ValidationReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)

  const locationName = useMemo(
    () => new Map(locations.map((l) => [l.id, l.name])),
    [locations],
  )
  // Non-revenue legs may start or end anywhere, but a depot/garage/layover is
  // what the validator expects at the ends of a block.
  const depotish = locations.filter((l) =>
    ['depot', 'garage', 'layover'].includes(l.location_type),
  )

  async function load() {
    setLoading(true)
    try {
      const detail = await api.get<Block>(`/blocks/${block.id}/detail`)
      setPieces(detail.pieces ?? [])
      setReport(await api.get<ValidationReport>(`/blocks/${block.id}/validate`))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [block.id])

  function update(index: number, patch: Partial<BlockPiece>) {
    setPieces(pieces.map((p, i) => (i === index ? { ...p, ...patch } : p)))
  }

  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= pieces.length) return
    const next = [...pieces]
    ;[next[index], next[target]] = [next[target], next[index]]
    setPieces(next)
  }

  function addPiece(type: BlockPieceType) {
    setPieces([
      ...pieces,
      {
        sequence: pieces.length + 1,
        piece_type: type,
        trip_id: null,
        from_location_id: null,
        to_location_id: null,
        start_seconds: null,
        end_seconds: null,
        notes: null,
      },
    ])
  }

  async function save() {
    setSaving(true)
    setError('')
    try {
      await api.put(`/blocks/${block.id}/pieces`, {
        pieces: pieces.map((piece, index) => ({
          sequence: index + 1,
          piece_type: piece.piece_type,
          trip_id: piece.piece_type === 'trip' ? piece.trip_id : null,
          from_location_id: piece.piece_type === 'trip' ? null : piece.from_location_id,
          to_location_id: piece.piece_type === 'trip' ? null : piece.to_location_id,
          start_seconds: piece.piece_type === 'trip' ? null : piece.start_seconds,
          end_seconds: piece.piece_type === 'trip' ? null : piece.end_seconds,
          notes: piece.notes,
        })),
      })
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      wide
      title={`Block ${block.name} — pieces`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Close</button>
          {canEdit && (
            <button className="primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save pieces'}
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
          <p className="small muted" style={{ marginTop: 0 }}>
            A trip piece takes its times and endpoints from the trip's own stop
            times — nothing is retyped here. Deadheads, pull-outs and pull-ins
            need their own two locations and times.
          </p>

          {pieces.length === 0 ? (
            <Empty>No pieces yet.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Type</th>
                    <th>From</th>
                    <th>To</th>
                    <th>Start</th>
                    <th>End</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pieces.map((piece, index) => {
                    const isTrip = piece.piece_type === 'trip'
                    return (
                      <tr key={index}>
                        <td className="num">{index + 1}</td>
                        <td style={{ minWidth: 130 }}>
                          {isTrip ? (
                            <>
                              <span className="tag">{piece.line_short_name ?? 'trip'}</span>{' '}
                              <span className="small muted">#{piece.trip_id}</span>
                            </>
                          ) : (
                            <select
                              value={piece.piece_type}
                              disabled={!canEdit}
                              onChange={(e) =>
                                update(index, { piece_type: e.target.value as BlockPieceType })
                              }
                            >
                              {PIECE_TYPES.filter((t) => t.value !== 'trip').map((t) => (
                                <option key={t.value} value={t.value}>
                                  {t.value.replace('_', '-')}
                                </option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td style={{ minWidth: 170 }}>
                          {isTrip ? (
                            <span className="small">{piece.effective_from_location_name ?? '—'}</span>
                          ) : (
                            <LocationPicker
                              value={piece.from_location_id}
                              onChange={(v) => update(index, { from_location_id: v })}
                              options={piece.piece_type === 'pull_out' ? depotish : locations}
                              disabled={!canEdit}
                            />
                          )}
                        </td>
                        <td style={{ minWidth: 170 }}>
                          {isTrip ? (
                            <span className="small">{piece.effective_to_location_name ?? '—'}</span>
                          ) : (
                            <LocationPicker
                              value={piece.to_location_id}
                              onChange={(v) => update(index, { to_location_id: v })}
                              options={piece.piece_type === 'pull_in' ? depotish : locations}
                              disabled={!canEdit}
                            />
                          )}
                        </td>
                        <td style={{ width: 105 }}>
                          {isTrip ? (
                            <span className="small nowrap">
                              {secondsToHhmm(piece.effective_start_seconds)}
                            </span>
                          ) : (
                            <TimeInput
                              value={piece.start_seconds}
                              onChange={(v) => update(index, { start_seconds: v || null })}
                            />
                          )}
                        </td>
                        <td style={{ width: 105 }}>
                          {isTrip ? (
                            <span className="small nowrap">
                              {secondsToHhmm(piece.effective_end_seconds)}
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
                              <button className="small" onClick={() => move(index, -1)} disabled={index === 0}>
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
              <button onClick={() => setPickerOpen(true)}>+ Add trip</button>
              <button onClick={() => addPiece('pull_out')}>+ Pull-out</button>
              <button onClick={() => addPiece('deadhead')}>+ Deadhead</button>
              <button onClick={() => addPiece('pull_in')}>+ Pull-in</button>
              <span className="muted small">
                Unsaved changes are validated after you save.
              </span>
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <h3 style={{ fontSize: 14 }}>Consistency check</h3>
            <p className="small muted" style={{ marginTop: 0 }}>
              Continuity is compared on real location ids, not on text. Issues
              are reported, never enforced — you can save regardless.
            </p>
            <IssueList report={report} />
          </div>
        </>
      )}

      {pickerOpen && (
        <TripPicker
          scheduleVersionId={block.schedule_version_id}
          lastLocationId={
            pieces.length
              ? pieces[pieces.length - 1].effective_to_location_id ??
                pieces[pieces.length - 1].to_location_id ??
                null
              : null
          }
          lastEnd={
            pieces.length
              ? pieces[pieces.length - 1].effective_end_seconds ??
                pieces[pieces.length - 1].end_seconds ??
                null
              : null
          }
          onClose={() => setPickerOpen(false)}
          onPick={(trip) => {
            setPieces((current) => [
              ...current,
              {
                sequence: current.length + 1,
                piece_type: 'trip',
                trip_id: trip.trip_id,
                from_location_id: null,
                to_location_id: null,
                start_seconds: null,
                end_seconds: null,
                notes: null,
                line_short_name: trip.line_short_name,
                effective_from_location_name: trip.from_location_name,
                effective_to_location_name: trip.to_location_name,
                effective_from_location_id: trip.from_location_id,
                effective_to_location_id: trip.to_location_id,
                effective_start_seconds: trip.start_seconds,
                effective_end_seconds: trip.end_seconds,
              },
            ])
            setPickerOpen(false)
          }}
        />
      )}
    </Modal>
  )
}

function LocationPicker({
  value,
  onChange,
  options,
  disabled,
}: {
  value: number | null
  onChange: (v: number | null) => void
  options: Location[]
  disabled?: boolean
}) {
  return (
    <select
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      <option value="">— choose —</option>
      {options.map((l) => (
        <option key={l.id} value={l.id}>
          {l.name} ({l.location_type})
        </option>
      ))}
    </select>
  )
}

function TripPicker({
  scheduleVersionId,
  lastLocationId,
  lastEnd,
  onClose,
  onPick,
}: {
  scheduleVersionId: number
  lastLocationId: number | null
  lastEnd: string | null
  onClose: () => void
  onPick: (trip: UnassignedTrip) => void
}) {
  const params = useMemo(
    () => ({ schedule_version_id: scheduleVersionId }),
    [scheduleVersionId],
  )
  const { items, loading, error } = useList<UnassignedTrip>('/fleet/unassigned-trips', params)
  const [onlyConnecting, setOnlyConnecting] = useState(!!lastLocationId)

  // "Connecting" = starts where the block currently is, and not before it
  // gets there. That is the shortlist a scheduler actually wants.
  const shown = items.filter((trip) => {
    if (!onlyConnecting || !lastLocationId) return true
    if (trip.from_location_id !== lastLocationId) return false
    if (lastEnd && trip.start_seconds && trip.start_seconds < lastEnd) return false
    return true
  })

  return (
    <Modal wide title="Add a trip to the block" onClose={onClose}>
      <Alert kind="err">{error}</Alert>
      <div className="toolbar">
        <div className="field inline">
          <input
            type="checkbox"
            checked={onlyConnecting}
            disabled={!lastLocationId}
            onChange={(e) => setOnlyConnecting(e.target.checked)}
          />
          <label>
            Only trips that connect
            {lastLocationId ? '' : ' (add a first piece to enable)'}
          </label>
        </div>
        <span className="spacer" />
        <span className="muted small">{shown.length} of {items.length} unassigned</span>
      </div>

      {loading ? (
        <Spinner />
      ) : shown.length === 0 ? (
        <Empty>
          {items.length === 0
            ? 'Every trip on this board is already in a block.'
            : 'No unassigned trip connects here. Insert a deadhead first, or untick the filter.'}
        </Empty>
      ) : (
        <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
          <table className="grid">
            <thead>
              <tr>
                <th>Line</th>
                <th>Headsign</th>
                <th>From</th>
                <th>To</th>
                <th>Departs</th>
                <th>Arrives</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((trip) => (
                <tr key={trip.trip_id}>
                  <td>
                    <span className="tag">{trip.line_short_name}</span>
                  </td>
                  <td>{trip.headsign}</td>
                  <td className="small">{trip.from_location_name}</td>
                  <td className="small">{trip.to_location_name}</td>
                  <td className="nowrap">{secondsToHhmm(trip.start_seconds)}</td>
                  <td className="nowrap">{secondsToHhmm(trip.end_seconds)}</td>
                  <td className="actions">
                    <button className="small primary" onClick={() => onPick(trip)}>
                      Add
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  )
}
