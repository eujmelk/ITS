import { useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Calendar, ScheduleVersion } from '../api/types'
import { CrudTable, useList } from '../components/Crud'
import type { Column } from '../components/Crud'
import { Alert, Field, Modal, PageHead, Panel } from '../components/ui'
import { useApp } from '../state/AppContext'

const DAYS: (keyof Calendar)[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]

export default function BoardsPage() {
  const { canEdit } = useApp()
  const [selected, setSelected] = useState<ScheduleVersion | null>(null)
  const { items: boards, reload } = useList<ScheduleVersion>('/schedule-versions')

  const columns: Column<ScheduleVersion>[] = [
    { key: 'name', label: 'Board', sortKey: 'name' },
    { key: 'start_date', label: 'From', sortKey: 'start_date' },
    { key: 'end_date', label: 'To', sortKey: 'end_date' },
    {
      key: 'status',
      label: 'Status',
      sortKey: 'status',
      render: (row) => (
        <span className={`tag ${row.status === 'active' ? 'ok' : row.status === 'archived' ? 'grey' : ''}`}>
          {row.status}
        </span>
      ),
    },
    { key: 'trip_count', label: 'Trips', numeric: true },
    { key: 'block_count', label: 'Blocks', numeric: true },
  ]

  return (
    <>
      <PageHead
        title="Schedule boards"
        info="A board is everything valid over one date range: its calendars, its trips and its blocks. Next season starts as a copy of this one."
      />

      <Panel>
        <CrudTable<ScheduleVersion>
          endpoint="/schedule-versions"
          entityName="Board"
          columns={columns}
          fields={[
            { name: 'name', label: 'Name', required: true },
            {
              name: 'status',
              label: 'Status',
              type: 'select',
              options: ['draft', 'active', 'archived'].map((s) => ({ value: s, label: s })),
            },
            { name: 'start_date', label: 'Valid from', type: 'date', required: true },
            { name: 'end_date', label: 'Valid to', type: 'date', required: true },
            { name: 'description', label: 'Description', type: 'textarea' },
          ]}
          defaults={{ status: 'draft' }}
          onChanged={reload}
          extraRowActions={(row) => (
            <>
              <button className="small" onClick={() => setSelected(row)}>
                Calendars
              </button>{' '}
              <GtfsButton board={row} />{' '}
              {canEdit && <DuplicateButton board={row} onDone={reload} />}
            </>
          )}
        />
      </Panel>

      {selected && (
        <CalendarsPanel board={selected} onClose={() => setSelected(null)} />
      )}
    </>
  )
}

/**
 * GTFS export, gated behind a pre-flight check.
 *
 * A feed that a reader rejects is worse than no feed, so the problems are
 * shown first — but exporting anyway is allowed, because a feed missing an
 * agency URL is still useful for inspecting the data.
 */
function GtfsButton({ board }: { board: ScheduleVersion }) {
  const [open, setOpen] = useState(false)
  const [problems, setProblems] = useState<string[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function check() {
    setOpen(true)
    setError('')
    setProblems(null)
    try {
      setProblems(await api.get<string[]>('/gtfs/validate', { schedule_version_id: board.id }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function download() {
    setBusy(true)
    setError('')
    try {
      await api.downloadBlob('/gtfs/export', `gtfs_${board.name.replace(/\W+/g, '_')}.zip`, {
        schedule_version_id: board.id,
      })
      setOpen(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="small" onClick={check} title="Export a GTFS feed">
        GTFS
      </button>
      {open && (
        <Modal
          title={`GTFS export — ${board.name}`}
          info="A standards-compliant zip: stops, routes, trips, stop times, calendars, transfers and fares. Only passenger-facing data — depots, blocks and duties stay internal. Stop areas become GTFS parent stations, and skipped stops are simply absent from stop_times.txt."
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" onClick={download} disabled={busy}>
                {busy ? 'Building…' : 'Download feed'}
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          {problems === null ? (
            <p className="muted">Checking…</p>
          ) : problems.length === 0 ? (
            <div className="alert ok">No problems found — the feed is ready.</div>
          ) : (
            <>
              <div className="alert info">
                These will not stop the export, but a strict reader may reject
                the feed:
              </div>
              {problems.map((problem, index) => (
                <div key={index} className="issue warning">
                  {problem}
                </div>
              ))}
            </>
          )}
        </Modal>
      )}
    </>
  )
}

function DuplicateButton({ board, onDone }: { board: ScheduleVersion; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(`${board.name} (copy)`)
  const [includeTrips, setIncludeTrips] = useState(true)
  const [includeBlocks, setIncludeBlocks] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true)
    setError('')
    try {
      await api.post(`/schedule-versions/${board.id}/duplicate`, undefined, {
        name,
        include_trips: includeTrips,
        include_blocks: includeBlocks,
      })
      setOpen(false)
      onDone()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="small" onClick={() => setOpen(true)}>
        Copy
      </button>
      {open && (
        <Modal
          title={`Copy board — ${board.name}`}
          info="Blocks reference specific trips, so they can only be copied along with them. Calendars and their exception dates always come across. The copy is created as a draft."
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button className="primary" onClick={run} disabled={busy || !name.trim()}>
                {busy ? 'Copying…' : 'Create copy'}
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <Field label="New board name">
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="field inline">
            <input
              type="checkbox"
              checked={includeTrips}
              onChange={(e) => {
                setIncludeTrips(e.target.checked)
                if (!e.target.checked) setIncludeBlocks(false)
              }}
            />
            <label>Copy trips and stop times</label>
          </div>
          <div className="field inline">
            <input
              type="checkbox"
              checked={includeBlocks}
              disabled={!includeTrips}
              onChange={(e) => setIncludeBlocks(e.target.checked)}
            />
            <label>Copy blocks too</label>
          </div>
        </Modal>
      )}
    </>
  )
}

function CalendarsPanel({ board, onClose }: { board: ScheduleVersion; onClose: () => void }) {
  const params = useMemo(() => ({ schedule_version_id: board.id }), [board.id])

  return (
    <Panel
      title={`Calendars — ${board.name}`}
      hint="which days each group of trips runs"
      info="A calendar is a service pattern — weekdays, Saturday, school holidays — and every trip belongs to one. Individual dates can be added or removed per calendar through the API (/calendar-exceptions) for public holidays and one-off events."
      actions={
        <button className="small" onClick={onClose}>
          Close
        </button>
      }
    >
      <CrudTable<Calendar>
        endpoint="/calendars"
        entityName="Calendar"
        params={params}
        searchable={false}
        defaults={{
          schedule_version_id: board.id,
          monday: true,
          tuesday: true,
          wednesday: true,
          thursday: true,
          friday: true,
        }}
        toPayload={(values, mode) =>
          mode === 'create' ? { ...values, schedule_version_id: board.id } : values
        }
        columns={[
          { key: 'name', label: 'Calendar' },
          {
            key: 'days',
            label: 'Runs on',
            render: (row) => {
              const active = DAYS.filter((d) => (row as any)[d]).map((d) =>
                String(d).slice(0, 3).replace(/^./, (c) => c.toUpperCase()),
              )
              return active.length ? active.join(' ') : <span className="tag warn">no days set</span>
            },
          },
          { key: 'start_date', label: 'From' },
          { key: 'end_date', label: 'To' },
        ]}
        fields={[
          { name: 'name', label: 'Name', required: true, hint: 'e.g. Weekdays, Saturday, School holidays' },
          { name: 'start_date', label: 'From (optional)', type: 'date' },
          { name: 'end_date', label: 'To (optional)', type: 'date' },
          ...DAYS.map((day) => ({
            name: String(day),
            label: String(day).replace(/^./, (c) => c.toUpperCase()),
            type: 'checkbox' as const,
          })),
        ]}
      />
    </Panel>
  )
}
