import { useMemo, useState } from 'react'
import type { Location, TransferEdge } from '../api/types'
import { useList } from '../components/Crud'
import { Empty, Field, PageHead, Panel, Spinner } from '../components/ui'

/**
 * Phase 11 (the journey search) is not implemented. What is implemented is the
 * part the v3 revision actually changed: the transfer graph the search will
 * walk. Showing it here makes the connectivity model inspectable before any
 * search exists to consume it.
 */
export default function ItineraryPage() {
  const { items: locations } = useList<Location>('/locations', { location_type: 'stop' })
  const { items: edges, loading } = useList<TransferEdge>('/location-transfers/graph/edges')
  const [focus, setFocus] = useState('')

  const names = useMemo(() => new Map(locations.map((l) => [l.id, l.name])), [locations])
  const shown = focus
    ? edges.filter(
        (e) => String(e.from_location_id) === focus || String(e.to_location_id) === focus,
      )
    : edges

  return (
    <>
      <PageHead
        title="Itinerary finder"
        intro="Journey search between two stops."
      />

      <Panel title="Search">
        <div className="alert info" style={{ marginBottom: 0 }}>
          <strong>Not in this build.</strong>
          <p style={{ margin: '6px 0 0' }}>
            The search itself is phase 11. <code>POST /api/v1/itinerary/search</code>{' '}
            is published with its final request and response models and returns{' '}
            <code>501</code>.
          </p>
        </div>
      </Panel>

      <Panel title="Transfer graph" hint="the walking edges the search will use">
        <p className="small muted" style={{ marginTop: 0 }}>
          Exactly two sources feed this: stops sharing a stop area, at that
          area's cross time; and explicit pairwise transfer rows. Coordinate
          proximity never creates an edge — two points can be 40 m apart with a
          motorway between them.
        </p>

        <div className="toolbar">
          <Field label="Focus on one stop">
            <select value={focus} onChange={(e) => setFocus(e.target.value)}>
              <option value="">All stops</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </Field>
          <span className="spacer" />
          <span className="muted small" style={{ marginTop: 18 }}>
            {shown.length} edges
          </span>
        </div>

        {loading ? (
          <Spinner />
        ) : shown.length === 0 ? (
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
                {shown.map((edge, index) => (
                  <tr key={index}>
                    <td>{names.get(edge.from_location_id) ?? edge.from_location_id}</td>
                    <td>{names.get(edge.to_location_id) ?? edge.to_location_id}</td>
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
        )}
      </Panel>
    </>
  )
}
