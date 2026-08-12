import { useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type {
  FareZone,
  ImportReport,
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
import { EntitySelect } from '../components/EntitySelect'
import { MapView } from '../components/MapView'
import { Alert, Empty, Field, IssueList, Modal, PageHead, Panel, Spinner } from '../components/ui'
import { useApp } from '../state/AppContext'

const TYPES = ['stop', 'depot', 'layover', 'garage', 'other']

type Tab = 'locations' | 'areas' | 'transfers' | 'quality'

export default function LocationsPage() {
  const { canEdit } = useApp()
  const [tab, setTab] = useState<Tab>('locations')
  const [reloadKey, setReloadKey] = useState(0)

  // Reference data small enough to hold whole. Locations are NOT: they are
  // fetched with an explicit cap for the map only, and `truncated` says so
  // out loud rather than quietly drawing a subset.
  const MAP_CAP = 2000
  const mapParams = useMemo(() => ({ limit: MAP_CAP }), [])
  const {
    items: locations,
    total: locationTotal,
    truncated: mapTruncated,
    reload: reloadLocations,
  } = useList<Location>('/locations', mapParams)
  const { items: zones } = useList<FareZone>('/fare-zones', undefined)
  const { items: areas, reload: reloadAreas } = useList<StopArea>('/stop-areas')

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
      type: 'entity',
      endpoint: '/stop-areas',
      hint: 'stop-type locations only',
    },
    { name: 'is_active', label: 'Active', type: 'checkbox' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ]

  const columns: Column<Location>[] = [
    { key: 'name', label: 'Name', sortKey: 'name' },
    { key: 'code', label: 'Code', sortKey: 'code' },
    {
      key: 'location_type',
      label: 'Type',
      sortKey: 'location_type',
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
        info="Stops, depots, layover points and garages live in one table with a type flag — they are operationally the same kind of thing, a place with a name and coordinates."
        actions={
          <>
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
            <span className="sep" />
            <button onClick={() => api.downloadBlob('/csv/locations', 'locations.csv')}>
              Export CSV
            </button>
            {canEdit && (
              <ImportButton
                onDone={() => {
                  reloadLocations()
                  setReloadKey((k) => k + 1)
                }}
              />
            )}
          </>
        }
      />

      {tab === 'locations' && (
        <div className="cols side">
          <Panel>
            <CrudTable<Location>
              endpoint="/locations"
              entityName="Location"
              columns={columns}
              fields={fields}
              refreshToken={reloadKey}
              defaults={{ location_type: 'stop', is_active: true }}
              onChanged={() => {
                reloadLocations()
                setReloadKey((k) => k + 1)
              }}
              extraRowActions={(row) =>
                canEdit ? (
                  <AttributesButton
                    location={row}
                    onSaved={() => {
                      reloadLocations()
                      setReloadKey((k) => k + 1)
                    }}
                  />
                ) : null
              }
            />
          </Panel>
          <Panel
            title="Reference map"
            hint={mapTruncated ? `first ${MAP_CAP.toLocaleString()} of ${locationTotal.toLocaleString()}` : 'colour by type'}
            info={
              mapTruncated
                ? `Markers are coloured by location type. Only the first ${MAP_CAP.toLocaleString()} of ${locationTotal.toLocaleString()} locations are mapped, and only those in view are drawn — use the table's search to find a specific one.`
                : 'Markers are coloured by location type. Only locations in view are drawn, so panning a large network stays responsive.'
            }
          >
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

      {tab === 'areas' && <StopAreasPanel areas={areas} reload={reloadAreas} />}

      {tab === 'transfers' && <TransfersPanel />}

      {tab === 'quality' && <QualityPanel />}
    </>
  )
}

/* ---------------------------------------------------------- CSV import */

/**
 * Two-step import: a dry run first, then apply.
 *
 * The dry run is a real pass over the file — every row is parsed, matched and
 * written inside a transaction that is then rolled back — so the counts shown
 * are what will actually happen, not a guess from reading the header.
 */
function ImportButton({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [replaceAttributes, setReplaceAttributes] = useState(false)
  const [report, setReport] = useState<ImportReport | null>(null)
  const [applied, setApplied] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  function reset() {
    setFile(null)
    setReport(null)
    setApplied(false)
    setError('')
  }

  async function send(dryRun: boolean) {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const result = await api.upload<ImportReport>('/locations/import', file, {
        dry_run: dryRun,
        replace_attributes: replaceAttributes,
      })
      setReport(result)
      if (!dryRun && result.ok) {
        setApplied(true)
        onDone()
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const failures = report?.rows.filter((r) => r.action === 'failed') ?? []

  return (
    <>
      <button
        onClick={() => {
          reset()
          setOpen(true)
        }}
      >
        Import CSV…
      </button>

      {open && (
        <Modal
          wide
          title="Import locations from CSV"
          info={
            'Round-trips the export: download the CSV, edit it in a spreadsheet, ' +
            'upload it back. Rows are matched on id, then code; anything ' +
            'unmatched is created. Blank cells leave the existing value alone, ' +
            'so a sheet holding only code plus lat/lon is a safe way to add ' +
            'coordinates in bulk. Unrecognised columns become location ' +
            'attributes. Nothing is written unless the whole file is clean.'
          }
          onClose={() => setOpen(false)}
          footer={
            <>
              <button
                onClick={() =>
                  api.downloadBlob('/csv/locations', 'locations.csv')
                }
              >
                Download current as template
              </button>
              <span className="spacer" />
              <button onClick={() => setOpen(false)}>Close</button>
              <button onClick={() => send(true)} disabled={!file || busy}>
                {busy ? 'Checking…' : 'Check file'}
              </button>
              <button
                className="primary"
                disabled={!report || !report.ok || report.total === 0 || busy || applied}
                onClick={() => send(false)}
              >
                Apply
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          {applied && <Alert kind="ok">Import applied.</Alert>}

          <div className="field">
            <label>CSV file</label>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setReport(null)
                setApplied(false)
              }}
            />
          </div>
          <div className="field inline">
            <input
              type="checkbox"
              checked={replaceAttributes}
              onChange={(e) => setReplaceAttributes(e.target.checked)}
            />
            <label>
              This file is the whole truth for attributes (remove any not listed)
            </label>
          </div>

          {report?.fatal && <Alert kind="err">{report.fatal}</Alert>}

          {report && !report.fatal && (
            <fieldset className="group">
              <legend>{report.dry_run ? 'Dry run — nothing written' : 'Result'}</legend>
              <div className="toolbar-row">
                <span className="tag">{report.total} rows</span>
                <span className="tag ok">{report.created} new</span>
                <span className="tag">{report.updated} updated</span>
                <span className="tag grey">{report.skipped} unchanged</span>
                {report.failed > 0 && (
                  <span className="tag err">{report.failed} failed</span>
                )}
                <span className="spacer" />
                <span className="small muted">
                  read as “{report.delimiter}”-separated
                </span>
              </div>

              {report.attribute_columns.length > 0 && (
                <p className="small" style={{ margin: '0 0 4px' }}>
                  <span className="muted">Columns treated as attributes: </span>
                  {report.attribute_columns.join(', ')}
                </p>
              )}

              {failures.length > 0 && (
                <div className="table-wrap" style={{ maxHeight: 220, overflowY: 'auto' }}>
                  <table className="grid">
                    <thead>
                      <tr>
                        <th className="num">Line</th>
                        <th>Name</th>
                        <th>Code</th>
                        <th>Problem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {failures.map((row) => (
                        <tr key={row.line}>
                          <td className="num">{row.line}</td>
                          <td>{row.name}</td>
                          <td>{row.code}</td>
                          <td>{row.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {report.failed > 0 && (
                <Alert kind="err">
                  Fix these lines and check again — nothing is written while any
                  row fails.
                </Alert>
              )}
            </fieldset>
          )}
        </Modal>
      )}
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
          info="Free-form key/value pairs. Add whatever you need — no schema change or release is involved."
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

function StopAreasPanel({ areas, reload }: { areas: StopArea[]; reload: () => void }) {
  const { canEdit } = useApp()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [members, setMembers] = useState<{ id: number; name: string }[]>([])
  const [error, setError] = useState('')

  const editing = areas.find((a) => a.id === editingId) ?? null

  async function saveMembers() {
    if (!editing) return
    setError('')
    try {
      await api.put(`/stop-areas/${editing.id}/members`, {
        location_ids: members.map((m) => m.id),
      })
      setEditingId(null)
      reload()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <Panel
      title="Stop areas"
      info="A stop area groups locations that are effectively the same place — two directions of one street, opposite corners of a junction. Membership is flagged once per stop, so any two members are automatically connected by a transfer at the area's cross time. Adding a third stop on the same corner needs no new pairwise rows."
    >
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
                setMembers(
                  (row.location_ids ?? []).map((id, index) => ({
                    id,
                    name: row.location_names?.[index] ?? `#${id}`,
                  })),
                )
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
          info="Only stop-type locations can join an area — a depot is not somewhere a passenger transfers. An area normally holds two or three stops, so search for them rather than scrolling the network."
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

          {members.length === 0 ? (
            <Empty>No member stops yet.</Empty>
          ) : (
            <table className="grid" style={{ marginBottom: 10 }}>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td>{member.name}</td>
                    <td className="actions">
                      <button
                        className="small danger"
                        onClick={() =>
                          setMembers(members.filter((m) => m.id !== member.id))
                        }
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <Field label="Add a stop">
            <EntitySelect
              endpoint="/locations"
              params={{ location_type: 'stop' }}
              value={null}
              placeholder="Search stops…"
              allowClear={false}
              onChange={async (id) => {
                if (id == null || members.some((m) => m.id === id)) return
                try {
                  const row = await api.get<Location>(`/locations/${id}`)
                  setMembers((current) => [...current, { id, name: row.name }])
                } catch {
                  setMembers((current) => [...current, { id, name: `#${id}` }])
                }
              }}
            />
          </Field>
        </Modal>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------------- transfers */

function TransfersPanel() {
  const [showGraph, setShowGraph] = useState(false)
  const { items: edges, loading } = useList<TransferEdge>(
    '/location-transfers/graph/edges',
    undefined,
    showGraph,
  )

  return (
    <>
      <Panel
        title="Transfers"
        info={`Explicit pairwise walks, for places that are not "the same place" but are still a reasonable connection — a bus stop and a rail platform 300 m apart, say. These should be rarer than stop areas.`}
      >
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
              type: 'entity',
              endpoint: '/locations',
              required: true,
            },
            {
              name: 'to_location_id',
              label: 'To location',
              type: 'entity',
              endpoint: '/locations',
              required: true,
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
        hint="what the itinerary finder sees"
        info="Two sources only: stop-area members at the area's cross time, and the explicit rows above. Nothing is inferred from coordinate proximity — a river or a motorway can sit between two points that look adjacent."
        actions={
          <button className="small" onClick={() => setShowGraph((v) => !v)}>
            {showGraph ? 'Hide' : 'Show'}
          </button>
        }
      >
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
      info="Flags locations without coordinates, patterns calling at non-stop locations, and empty stop areas. Nothing here blocks saving."
      actions={
        <button className="small primary" onClick={run} disabled={busy}>
          {busy ? 'Checking…' : 'Run checks'}
        </button>
      }
    >
      <Alert kind="err">{error}</Alert>
      {report ? <IssueList report={report} /> : <Empty>Not run yet.</Empty>}
    </Panel>
  )
}
