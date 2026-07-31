import { useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  FareZone,
  Location,
  LocationTransfer,
  StopArea,
  TransferEdge,
  ValidationReport,
} from '../api/types'
import { CrudTable, useList } from '../components/Crud'
// Types must be imported separately: `isolatedModules` transpiles each file
// on its own, so a type imported as a value survives into the bundle and
// blows up at runtime.
import type { Column, FormField } from '../components/Crud'
import {
  AttributeEditor,
  LOCATION_ATTRIBUTE_SUGGESTIONS,
} from '../components/AttributeEditor'
import { MapView } from '../components/MapView'
import { Alert, Empty, IssueList, Modal, PageHead, Panel, Spinner } from '../components/ui'
import { useApp } from '../state/AppContext'

const TYPES = ['stop', 'depot', 'layover', 'garage', 'other']

type Tab = 'locations' | 'areas' | 'transfers' | 'quality'

export default function LocationsPage() {
  const { canEdit } = useApp()
  const [tab, setTab] = useState<Tab>('locations')
  const [reloadKey, setReloadKey] = useState(0)

  const { items: locations, reload: reloadLocations } = useList<Location>('/locations')
  const { items: zones } = useList<FareZone>('/fare-zones')
  const { items: areas, reload: reloadAreas } = useList<StopArea>('/stop-areas')

  const locationOptions = useMemo(
    () =>
      locations.map((l) => ({
        value: l.id,
        label: `${l.name}${l.code ? ` (${l.code})` : ''} · ${l.location_type}`,
      })),
    [locations],
  )
  const stopOptions = useMemo(
    () => locations.filter((l) => l.location_type === 'stop'),
    [locations],
  )

  const fields: FormField[] = [
    { name: 'name', label: 'Name', required: true },
    { name: 'code', label: 'Code', hint: 'optional, must be unique' },
    {
      name: 'location_type',
      label: 'Type',
      type: 'select',
      required: true,
      options: TYPES.map((t) => ({ value: t, label: t })),
    },
    {
      name: 'zone_id',
      label: 'Fare zone',
      type: 'select',
      options: zones.map((z) => ({ value: z.id, label: z.name })),
      hint: 'stops only, normally',
    },
    { name: 'lat', label: 'Latitude', type: 'number', step: 'any' },
    { name: 'lon', label: 'Longitude', type: 'number', step: 'any' },
    {
      name: 'area_id',
      label: 'Stop area',
      type: 'select',
      options: areas.map((a) => ({ value: a.id, label: a.name })),
      hint: 'stop-type locations only',
    },
    { name: 'is_active', label: 'Active', type: 'checkbox' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ]

  const columns: Column<Location>[] = [
    { key: 'name', label: 'Name' },
    { key: 'code', label: 'Code' },
    {
      key: 'location_type',
      label: 'Type',
      render: (row) => <span className="tag grey">{row.location_type}</span>,
    },
    { key: 'zone_name', label: 'Zone' },
    { key: 'area_name', label: 'Stop area' },
    {
      key: 'coords',
      label: 'Coordinates',
      render: (row) =>
        row.lat != null && row.lon != null ? (
          <span className="small nowrap">
            {row.lat.toFixed(5)}, {row.lon.toFixed(5)}
          </span>
        ) : (
          <span className="tag warn">missing</span>
        ),
    },
    {
      key: 'attributes',
      label: 'Attributes',
      numeric: true,
      render: (row) => row.attributes?.length ?? 0,
    },
  ]

  return (
    <>
      <PageHead
        title="Locations"
        intro="Stops, depots, layover points and garages live in one table with a type flag — they are operationally the same kind of thing, a place with a name and coordinates."
      />

      <div className="toolbar">
        {(['locations', 'areas', 'transfers', 'quality'] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? 'primary' : ''} onClick={() => setTab(t)}>
            {t === 'locations'
              ? 'Locations'
              : t === 'areas'
                ? 'Stop areas'
                : t === 'transfers'
                  ? 'Transfers'
                  : 'Data quality'}
          </button>
        ))}
      </div>

      {tab === 'locations' && (
        <div className="cols side">
          <Panel>
            <CrudTable<Location>
              endpoint="/locations"
              entityName="Location"
              columns={columns}
              fields={fields}
              defaults={{ location_type: 'stop', is_active: true }}
              onChanged={() => {
                reloadLocations()
                setReloadKey((k) => k + 1)
              }}
              extraRowActions={(row) =>
                canEdit ? <AttributesButton location={row} onSaved={reloadLocations} /> : null
              }
            />
          </Panel>
          <Panel title="Reference map" hint="colour by type">
            <MapView
              key={reloadKey}
              points={locations
                .filter((l) => l.lat != null && l.lon != null)
                .map((l) => ({
                  id: l.id,
                  name: l.name,
                  lat: l.lat as number,
                  lon: l.lon as number,
                  kind: l.location_type,
                  subtitle: `${l.location_type}${l.area_name ? ` · ${l.area_name}` : ''}`,
                }))}
            />
          </Panel>
        </div>
      )}

      {tab === 'areas' && (
        <StopAreasPanel areas={areas} stops={stopOptions} reload={reloadAreas} />
      )}

      {tab === 'transfers' && (
        <TransfersPanel locationOptions={locationOptions} />
      )}

      {tab === 'quality' && <QualityPanel />}
    </>
  )
}

/* ------------------------------------------------------------ attributes */

function AttributesButton({ location, onSaved }: { location: Location; onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState(location.attributes ?? [])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    setSaving(true)
    setError('')
    try {
      await api.patch(`/locations/${location.id}`, {
        attributes: rows
          .filter((r) => r.attribute_key.trim())
          .map((r) => ({ attribute_key: r.attribute_key.trim(), attribute_value: r.attribute_value })),
      })
      setOpen(false)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <button
        className="small"
        onClick={() => {
          setRows(location.attributes ?? [])
          setOpen(true)
        }}
      >
        Attributes
      </button>
      {open && (
        <Modal
          title={`Attributes — ${location.name}`}
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" onClick={save} disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <p className="small muted" style={{ marginTop: 0 }}>
            Free-form key/value pairs. Add whatever you need — no schema change
            or release is involved.
          </p>
          <AttributeEditor
            value={rows}
            onChange={setRows}
            suggestions={LOCATION_ATTRIBUTE_SUGGESTIONS}
          />
        </Modal>
      )}
    </>
  )
}

/* ------------------------------------------------------------ stop areas */

function StopAreasPanel({
  areas,
  stops,
  reload,
}: {
  areas: StopArea[]
  stops: Location[]
  reload: () => void
}) {
  const { canEdit } = useApp()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [error, setError] = useState('')

  const editing = areas.find((a) => a.id === editingId) ?? null

  async function saveMembers() {
    if (!editing) return
    setError('')
    try {
      await api.put(`/stop-areas/${editing.id}/members`, { location_ids: selected })
      setEditingId(null)
      reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Panel>
      <p className="small muted" style={{ marginTop: 0 }}>
        A stop area groups locations that are effectively the same place — two
        directions of one street, opposite corners of a junction. Membership is
        flagged once per stop, so any two members are automatically connected
        by a transfer at the area's cross time. Adding a third stop on the same
        corner needs no new pairwise rows.
      </p>
      <CrudTable<StopArea>
        endpoint="/stop-areas"
        entityName="Stop area"
        onChanged={reload}
        defaults={{ default_transfer_seconds: 120 }}
        columns={[
          { key: 'name', label: 'Name' },
          {
            key: 'default_transfer_seconds',
            label: 'Cross time',
            numeric: true,
            render: (row) => `${Math.round(row.default_transfer_seconds / 60)} min`,
          },
          {
            key: 'members',
            label: 'Member stops',
            render: (row) =>
              row.location_names?.length ? (
                row.location_names.join(', ')
              ) : (
                <span className="tag warn">none yet</span>
              ),
          },
        ]}
        fields={[
          { name: 'name', label: 'Name', required: true, hint: 'e.g. "Strawberry Rd & Main St"' },
          {
            name: 'default_transfer_seconds',
            label: 'Cross time (seconds)',
            type: 'number',
            hint: '90–120s covers crossing a street',
          },
          { name: 'notes', label: 'Notes', type: 'textarea' },
        ]}
        extraRowActions={(row) =>
          canEdit ? (
            <button
              className="small"
              onClick={() => {
                setEditingId(row.id)
                setSelected(row.location_ids ?? [])
                setError('')
              }}
            >
              Members
            </button>
          ) : null
        }
      />

      {editing && (
        <Modal
          title={`Member stops — ${editing.name}`}
          onClose={() => setEditingId(null)}
          footer={
            <>
              <button onClick={() => setEditingId(null)}>Cancel</button>
              <button className="primary" onClick={saveMembers}>
                Save membership
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <p className="small muted" style={{ marginTop: 0 }}>
            Only stop-type locations can join an area — a depot is not
            somewhere a passenger transfers.
          </p>
          <div style={{ maxHeight: 340, overflowY: 'auto' }}>
            {stops.length === 0 && <Empty>No stop-type locations exist yet.</Empty>}
            {stops.map((stop) => (
              <div className="field inline" key={stop.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(stop.id)}
                  onChange={(e) =>
                    setSelected((current) =>
                      e.target.checked
                        ? [...current, stop.id]
                        : current.filter((id) => id !== stop.id),
                    )
                  }
                />
                <label>
                  {stop.name} {stop.code && <span className="muted">({stop.code})</span>}
                  {stop.area_id && stop.area_id !== editing.id && (
                    <span className="tag warn" style={{ marginLeft: 6 }}>
                      in {stop.area_name}
                    </span>
                  )}
                </label>
              </div>
            ))}
          </div>
        </Modal>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------------- transfers */

function TransfersPanel({
  locationOptions,
}: {
  locationOptions: { value: number; label: string }[]
}) {
  const [showGraph, setShowGraph] = useState(false)
  const { items: edges, loading } = useList<TransferEdge>(
    '/location-transfers/graph/edges',
    undefined,
    showGraph,
  )
  const names = new Map(locationOptions.map((o) => [o.value, o.label]))

  return (
    <>
      <Panel>
        <p className="small muted" style={{ marginTop: 0 }}>
          Explicit pairwise walks, for places that are not "the same place" but
          are still a reasonable connection — a bus stop and a rail platform
          300 m apart, say. These should be rarer than stop areas.
        </p>
        <CrudTable<LocationTransfer>
          endpoint="/location-transfers"
          entityName="Transfer"
          searchable={false}
          defaults={{ walk_seconds: 180, is_bidirectional: true }}
          columns={[
            { key: 'from_location_name', label: 'From' },
            { key: 'to_location_name', label: 'To' },
            {
              key: 'walk_seconds',
              label: 'Walk',
              numeric: true,
              render: (row) => `${Math.round(row.walk_seconds / 60)} min`,
            },
            { key: 'distance_m', label: 'Distance (m)', numeric: true },
            {
              key: 'is_bidirectional',
              label: 'Both ways',
              render: (row) => (row.is_bidirectional ? 'Yes' : 'One way'),
            },
          ]}
          fields={[
            {
              name: 'from_location_id',
              label: 'From location',
              type: 'select',
              required: true,
              options: locationOptions,
            },
            {
              name: 'to_location_id',
              label: 'To location',
              type: 'select',
              required: true,
              options: locationOptions,
            },
            { name: 'walk_seconds', label: 'Walk time (seconds)', type: 'number' },
            { name: 'distance_m', label: 'Distance (m)', type: 'number' },
            { name: 'is_bidirectional', label: 'Works both ways', type: 'checkbox' },
            { name: 'notes', label: 'Notes', type: 'textarea' },
          ]}
        />
      </Panel>

      <Panel
        title="Resolved transfer graph"
        hint="what the itinerary finder will see"
        actions={
          <button className="small" onClick={() => setShowGraph((v) => !v)}>
            {showGraph ? 'Hide' : 'Show'}
          </button>
        }
      >
        <p className="small muted" style={{ marginTop: 0 }}>
          Two sources only: stop-area members at the area's cross time, and the
          explicit rows above. Nothing is inferred from coordinate proximity —
          a river or a motorway can sit between two points that look adjacent.
        </p>
        {showGraph &&
          (loading ? (
            <Spinner />
          ) : edges.length === 0 ? (
            <Empty>No walking connections are defined.</Empty>
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
          ))}
      </Panel>
    </>
  )
}

/* --------------------------------------------------------------- quality */

function QualityPanel() {
  const [report, setReport] = useState<ValidationReport | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError('')
    try {
      setReport(await api.get<ValidationReport>('/locations/validate/report'))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      title="Data quality"
      actions={
        <button className="small primary" onClick={run} disabled={busy}>
          {busy ? 'Checking…' : 'Run checks'}
        </button>
      }
    >
      <p className="small muted" style={{ marginTop: 0 }}>
        Flags locations without coordinates, patterns calling at non-stop
        locations, and empty stop areas. Nothing here blocks saving.
      </p>
      <Alert kind="err">{error}</Alert>
      {report ? <IssueList report={report} /> : <Empty>Not run yet.</Empty>}
    </Panel>
  )
}
