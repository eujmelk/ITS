import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { FareMatrix, FareZone } from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import { EntitySelect } from '../components/EntitySelect'
import { Alert, Empty, Field, Modal, PageHead, Panel, Spinner, money } from '../components/ui'
import { useApp } from '../state/AppContext'

export default function FaresPage() {
  const { canEdit } = useApp()
  const { items: zones, reload: reloadZones } = useList<FareZone>('/fare-zones')
  const [matrix, setMatrix] = useState<FareMatrix | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [fillOpen, setFillOpen] = useState(false)

  async function loadMatrix() {
    setLoading(true)
    setError('')
    try {
      setMatrix(await api.get<FareMatrix>('/fares/matrix'))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMatrix()
  }, [])

  return (
    <>
      <PageHead
        title="Fares"
        info="Price is a function of origin zone and destination zone. A same-zone journey (A→A) is simply the diagonal of the matrix — it needs no special rule."
        actions={
          canEdit ? (
            <button onClick={() => setFillOpen(true)} disabled={!zones.length}>
              Bulk-fill empty cells
            </button>
          ) : null
        }
      />

      <div className="cols two">
        <Panel title="Zones">
          <CrudTable<FareZone>
            endpoint="/fare-zones"
            entityName="Zone"
            onChanged={() => {
              reloadZones()
              loadMatrix()
            }}
            columns={[
              { key: 'name', label: 'Zone' },
              { key: 'code', label: 'Code' },
              { key: 'location_count', label: 'Locations', numeric: true },
              { key: 'description', label: 'Description' },
            ]}
            fields={[
              { name: 'name', label: 'Name', required: true },
              { name: 'code', label: 'Code' },
              { name: 'description', label: 'Description', type: 'textarea' },
            ]}
          />
        </Panel>

        <Panel title="Fare quote" hint="check a real origin/destination pair">
          <QuotePanel />
        </Panel>
      </div>

      <Panel
        title="Price matrix"
        hint={matrix ? `${matrix.missing_count} unpriced` : undefined}
        info="Rows are the origin zone, columns the destination. Type a price in euros and tab out to save. Highlighted cells have no rule yet. Past 25 zones the grid is not drawn by default — it is quadratic, so 40 zones is 1,600 editable cells."
        actions={
          <button className="small" onClick={loadMatrix}>
            Refresh
          </button>
        }
      >
        <Alert kind="err">{error}</Alert>
        {loading ? (
          <Spinner />
        ) : !matrix || matrix.zone_ids.length === 0 ? (
          <Empty>Create at least one fare zone.</Empty>
        ) : (
          <MatrixTable matrix={matrix} onChanged={loadMatrix} editable={canEdit} />
        )}
      </Panel>

      {fillOpen && (
        <FillModal
          onClose={() => setFillOpen(false)}
          onDone={() => {
            setFillOpen(false)
            loadMatrix()
          }}
        />
      )}
    </>
  )
}

/**
 * The matrix is inherently quadratic: 40 zones is 1,600 editable cells, which
 * is both slow to render and impossible to read. Past this many zones it is
 * hidden behind a confirmation, and bulk-fill plus the per-rule table are the
 * better tools.
 */
const MATRIX_ZONE_WARN = 25

function MatrixTable({
  matrix,
  onChanged,
  editable,
}: {
  matrix: FareMatrix
  onChanged: () => void
  editable: boolean
}) {
  const [busyCell, setBusyCell] = useState('')
  const [error, setError] = useState('')
  const [forceShow, setForceShow] = useState(false)

  const cellAt = (origin: number, destination: number) =>
    matrix.cells.find((c) => c.origin_zone_id === origin && c.destination_zone_id === destination)

  async function setPrice(origin: number, destination: number, euros: string) {
    const cents = Math.round(parseFloat(euros.replace(',', '.')) * 100)
    if (Number.isNaN(cents) || cents < 0) return
    const key = `${origin}-${destination}`
    setBusyCell(key)
    setError('')
    try {
      const existing = cellAt(origin, destination)
      if (existing?.rule_id) {
        await api.patch(`/fare-rules/${existing.rule_id}`, { price_cents: cents })
      } else {
        await api.post('/fare-rules', {
          origin_zone_id: origin,
          destination_zone_id: destination,
          price_cents: cents,
          currency: 'EUR',
        })
      }
      onChanged()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusyCell('')
    }
  }

  if (matrix.zone_ids.length > MATRIX_ZONE_WARN && !forceShow) {
    return (
      <div className="alert info">
        <strong>{matrix.zone_ids.length} zones</strong> means{' '}
        {(matrix.zone_ids.length ** 2).toLocaleString()} cells. That is slow to
        render and hard to read, so it is not drawn by default.{' '}
        {matrix.missing_count > 0 && (
          <>
            {matrix.missing_count.toLocaleString()} cells are still unpriced —
            “Bulk-fill empty cells” handles those in one step.
          </>
        )}
        <div style={{ marginTop: 8 }}>
          <button className="small" onClick={() => setForceShow(true)}>
            Show the full grid anyway
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
      <Alert kind="err">{error}</Alert>
      <div className="table-wrap">
        <table className="matrix">
          <thead>
            <tr>
              <th>from \ to</th>
              {matrix.zone_names.map((name, index) => (
                <th key={matrix.zone_ids[index]}>{name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.zone_ids.map((origin, rowIndex) => (
              <tr key={origin}>
                <th>{matrix.zone_names[rowIndex]}</th>
                {matrix.zone_ids.map((destination) => {
                  const cell = cellAt(origin, destination)
                  const key = `${origin}-${destination}`
                  const classes = [
                    origin === destination ? 'diag' : '',
                    cell?.price_cents == null ? 'missing' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <td key={destination} className={classes}>
                      {editable ? (
                        <input
                          defaultValue={
                            cell?.price_cents != null ? (cell.price_cents / 100).toFixed(2) : ''
                          }
                          placeholder="—"
                          disabled={busyCell === key}
                          onBlur={(e) => {
                            const current =
                              cell?.price_cents != null ? (cell.price_cents / 100).toFixed(2) : ''
                            if (e.target.value !== current) setPrice(origin, destination, e.target.value)
                          }}
                        />
                      ) : (
                        money(cell?.price_cents, cell?.currency ?? 'EUR') || '—'
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function FillModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [price, setPrice] = useState('2.50')
  const [sameZoneOnly, setSameZoneOnly] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError('')
    try {
      await api.post('/fares/matrix/fill', undefined, {
        price_cents: Math.round(parseFloat(price.replace(',', '.')) * 100),
        currency: 'EUR',
        only_same_zone: sameZoneOnly,
      })
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Fill empty cells"
      info="Only cells with no rule are written. Existing prices are never overwritten, so this is safe to run after adding a zone."
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? 'Filling…' : 'Fill'}
          </button>
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      <Field label="Price (EUR)">
        <input value={price} onChange={(e) => setPrice(e.target.value)} />
      </Field>
      <div className="field inline">
        <input
          type="checkbox"
          checked={sameZoneOnly}
          onChange={(e) => setSameZoneOnly(e.target.checked)}
        />
        <label>Same-zone journeys only (the diagonal)</label>
      </div>
    </Modal>
  )
}

function QuotePanel() {
  const [from, setFrom] = useState<number | null>(null)
  const [to, setTo] = useState<number | null>(null)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const stopParams = useMemo(() => ({ location_type: 'stop' }), [])

  async function run() {
    setError('')
    setResult(null)
    try {
      setResult(
        await api.get('/fares/quote', { from_location_id: from, to_location_id: to }),
      )
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <Alert kind="err">{error}</Alert>
      <Field label="From stop">
        <EntitySelect
          endpoint="/locations"
          params={stopParams}
          value={from}
          onChange={setFrom}
          placeholder="Search stops…"
          sublabelOf={(row) => row.zone_name}
        />
      </Field>
      <Field label="To stop">
        <EntitySelect
          endpoint="/locations"
          params={stopParams}
          value={to}
          onChange={setTo}
          placeholder="Search stops…"
          sublabelOf={(row) => row.zone_name}
        />
      </Field>
      <button onClick={run} disabled={!from || !to}>
        Get price
      </button>
      {result && (
        <div style={{ marginTop: 12 }}>
          {result.matched ? (
            <div className="alert ok">
              {money(result.price_cents, result.currency)}
            </div>
          ) : (
            <div className="alert info">{result.reason}</div>
          )}
        </div>
      )}
    </>
  )
}
