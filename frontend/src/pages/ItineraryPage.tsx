import { useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Itinerary, ItineraryResponse, TransferEdge } from '../api/types'
import { useList } from '../components/Crud'
import { EntitySelect } from '../components/EntitySelect'
import {
  Alert,
  Empty,
  Field,
  PageHead,
  Panel,
  Spinner,
  TimeInput,
  money,
  secondsToHhmm,
} from '../components/ui'

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export default function ItineraryPage() {
  const stopParams = useMemo(() => ({ location_type: 'stop' }), [])
  const [from, setFrom] = useState<number | null>(null)
  const [to, setTo] = useState<number | null>(null)
  const [date, setDate] = useState(todayIso())
  const [departAfter, setDepartAfter] = useState('08:00')
  const [maxTransfers, setMaxTransfers] = useState(3)
  const [minTransfer, setMinTransfer] = useState(0)

  const [results, setResults] = useState<Itinerary[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setSearching(true)
    setError('')
    setResults(null)
    try {
      const response = await api.post<ItineraryResponse>('/itinerary/search', {
        from_location_id: from,
        to_location_id: to,
        date,
        depart_after: departAfter || null,
        max_transfers: maxTransfers,
        min_transfer_seconds: minTransfer * 60,
        max_results: 5,
      })
      setResults(response.itineraries)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSearching(false)
    }
  }

  return (
    <>
      <PageHead
        title="Itinerary finder"
        info="Journey search on a real service date. Walking connections come only from stop areas and explicit transfers — never from how close two points look on a map."
      />

      <Panel title="Search">
        <div className="toolbar-row">
          <div style={{ minWidth: 220 }}>
            <Field label="From">
              <EntitySelect
                endpoint="/locations"
                params={stopParams}
                value={from}
                onChange={setFrom}
                placeholder="Search stops…"
              />
            </Field>
          </div>
          <div style={{ minWidth: 220 }}>
            <Field label="To">
              <EntitySelect
                endpoint="/locations"
                params={stopParams}
                value={to}
                onChange={setTo}
                placeholder="Search stops…"
              />
            </Field>
          </div>
          <Field label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Field label="Depart after">
            <TimeInput value={departAfter} onChange={setDepartAfter} />
          </Field>
          <Field label="Max changes">
            <input
              type="number"
              min={0}
              max={6}
              style={{ width: 70 }}
              value={maxTransfers}
              onChange={(e) => setMaxTransfers(Number(e.target.value))}
            />
          </Field>
          <Field label="Change time (min)">
            <input
              type="number"
              min={0}
              style={{ width: 80 }}
              value={minTransfer}
              onChange={(e) => setMinTransfer(Number(e.target.value))}
            />
          </Field>
          <button
            className="primary"
            style={{ marginTop: 14 }}
            onClick={run}
            disabled={!from || !to || from === to || searching}
          >
            {searching ? 'Searching…' : 'Find journeys'}
          </button>
        </div>
        <Alert kind="err">{error}</Alert>
      </Panel>

      {searching && <Spinner label="Scanning the day's connections…" />}

      {results !== null && !searching && (
        <Panel title="Results" hint={`${results.length} journeys`}>
          {results.length === 0 ? (
            <Empty>
              No journey found. Check that trips run on this date's calendar,
              and that the stops are connected by a line or a transfer.
            </Empty>
          ) : (
            results.map((itinerary, index) => (
              <ItineraryCard key={index} itinerary={itinerary} />
            ))
          )}
        </Panel>
      )}

      <TransferGraphPanel />
    </>
  )
}

function ItineraryCard({ itinerary }: { itinerary: Itinerary }) {
  const minutes = Math.round(itinerary.duration_seconds / 60)
  return (
    <div className="panel" style={{ marginBottom: 10 }}>
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <strong style={{ fontSize: 15 }}>
          {secondsToHhmm(itinerary.depart_seconds)} → {secondsToHhmm(itinerary.arrive_seconds)}
        </strong>
        <span className="tag grey">
          {Math.floor(minutes / 60) ? `${Math.floor(minutes / 60)}h ` : ''}
          {minutes % 60}m
        </span>
        <span className="tag grey">
          {itinerary.transfer_count === 0
            ? 'direct'
            : `${itinerary.transfer_count} change${itinerary.transfer_count > 1 ? 's' : ''}`}
        </span>
        {itinerary.fare_price_cents != null && (
          <span className="tag ok">
            {money(itinerary.fare_price_cents, itinerary.fare_currency ?? 'EUR')}
          </span>
        )}
      </div>

      <table className="grid">
        <tbody>
          {itinerary.legs.map((leg, index) => (
            <tr key={index}>
              <td className="nowrap" style={{ width: 62 }}>
                {secondsToHhmm(leg.depart_seconds)}
              </td>
              <td className="nowrap" style={{ width: 62 }}>
                {secondsToHhmm(leg.arrive_seconds)}
              </td>
              <td style={{ width: 90 }}>
                {leg.kind === 'ride' ? (
                  <span className="tag">{leg.line_short_name ?? 'line'}</span>
                ) : (
                  <span className="tag grey">walk</span>
                )}
              </td>
              <td>
                {leg.from_location_name} → {leg.to_location_name}
                {leg.kind === 'ride' ? (
                  <span className="muted small">
                    {leg.headsign ? ` towards ${leg.headsign}` : ''}
                    {leg.intermediate_stop_count > 0
                      ? ` · ${leg.intermediate_stop_count} stop${leg.intermediate_stop_count > 1 ? 's' : ''}`
                      : ''}
                  </span>
                ) : (
                  <span className="muted small">
                    {' '}
                    · {Math.round(leg.duration_seconds / 60)} min on foot
                    {leg.transfer_source === 'stop_area' ? ' (same stop area)' : ''}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TransferGraphPanel() {
  const [show, setShow] = useState(false)
  const { items: edges, loading } = useList<TransferEdge>(
    '/location-transfers/graph/edges',
    undefined,
    show,
  )

  return (
    <Panel
      title="Transfer graph"
      hint="the walking edges the search uses"
      info="Exactly two sources: stops sharing a stop area, at that area's cross time, and explicit pairwise transfer rows. If a change you expect is not happening, it is almost always missing from here."
      actions={
        <button className="small" onClick={() => setShow((v) => !v)}>
          {show ? 'Hide' : 'Show'}
        </button>
      }
    >
      {show &&
        (loading ? (
          <Spinner />
        ) : edges.length === 0 ? (
          <Empty>
            No walking connections defined. Group stops into a stop area, or add
            an explicit transfer, on the Locations page.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>From</th>
                  <th>To</th>
                  <th className="num">Walk</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {edges.map((edge, index) => (
                  <tr key={index}>
                    <td>{edge.from_location_name ?? edge.from_location_id}</td>
                    <td>{edge.to_location_name ?? edge.to_location_id}</td>
                    <td className="num">{Math.round(edge.walk_seconds / 60)} min</td>
                    <td>
                      <span className={`tag ${edge.source === 'explicit' ? '' : 'grey'}`}>
                        {edge.source === 'explicit' ? 'explicit pair' : 'stop area'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </Panel>
  )
}
