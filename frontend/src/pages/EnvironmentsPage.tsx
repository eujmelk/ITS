import { useState } from 'react'
import { api, ApiError, switchEnvironment } from '../api/client'
import type { Environment } from '../api/types'
import { Alert, ConfirmButton, Empty, Field, Modal, PageHead, Panel, Spinner } from '../components/ui'
import { useApp } from '../state/AppContext'

/**
 * Environments are cities or operations, one database each.
 *
 * Administrator-only, because creating one provisions a database and deleting
 * one can destroy it.
 */
export default function EnvironmentsPage() {
  const { environments, environment, reloadEnvironments } = useApp()
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError('')
    try {
      await fn()
      await reloadEnvironments()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <>
      <PageHead
        title="Environments"
        info={
          'Each environment is a separate city or operation with its own ' +
          'database — locations, lines, timetables, blocks and rosters are ' +
          'entirely separate between them. Users and their roles are shared: ' +
          'one login reaches every environment. Switching is in the ' +
          'Environments menu, and the one you are working in is always shown ' +
          'at the bottom right.'
        }
        actions={
          <button className="primary" onClick={() => setCreating(true)}>
            New environment…
          </button>
        }
      />

      <Panel
        title="Environments"
        hint={`${environments.length}`}
        info={
          'The key becomes part of the database name and cannot be changed ' +
          'afterwards; the display name can. The default environment is the ' +
          'one used when a request does not name one — including a fresh ' +
          'login on a new browser.'
        }
      >
        <Alert kind="err">{error}</Alert>

        {environments.length === 0 ? (
          <Spinner />
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Key</th>
                  <th>Database</th>
                  <th>Status</th>
                  <th>Notes</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {environments.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.name}</strong>
                      {row.key === environment?.key && (
                        <span className="tag ok" style={{ marginLeft: 4 }}>
                          current
                        </span>
                      )}
                    </td>
                    <td>
                      <code>{row.key}</code>
                    </td>
                    <td className="small muted">{row.database_name}</td>
                    <td>
                      {row.is_default && <span className="tag">default</span>}{' '}
                      {row.is_active ? (
                        <span className="tag ok">active</span>
                      ) : (
                        <span className="tag grey">disabled</span>
                      )}
                    </td>
                    <td className="small">{row.notes}</td>
                    <td className="actions nowrap">
                      {row.key !== environment?.key && row.is_active && (
                        <button className="small" onClick={() => switchEnvironment(row.key)}>
                          Switch to
                        </button>
                      )}{' '}
                      {!row.is_default && row.is_active && (
                        <button
                          className="small"
                          disabled={!!busy}
                          onClick={() =>
                            act('default', () =>
                              api.post(`/environments/${row.id}/make-default`),
                            )
                          }
                        >
                          Make default
                        </button>
                      )}{' '}
                      {row.key !== environment?.key && !row.is_default && (
                        <>
                          <button
                            className="small"
                            disabled={!!busy}
                            onClick={() =>
                              act('toggle', () =>
                                api.patch(`/environments/${row.id}`, {
                                  is_active: !row.is_active,
                                }),
                              )
                            }
                          >
                            {row.is_active ? 'Disable' : 'Enable'}
                          </button>{' '}
                          <DeleteButton environment={row} onDone={reloadEnvironments} />
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {creating && (
        <CreateModal
          onClose={() => setCreating(false)}
          onCreated={async () => {
            setCreating(false)
            await reloadEnvironments()
          }}
        />
      )}
    </>
  )
}

function CreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: () => void
}) {
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function create() {
    setBusy(true)
    setError('')
    try {
      await api.post('/environments', { key, name, notes: notes || null })
      onCreated()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="New environment"
      info={
        'Creates a database, builds the schema and seeds the operating ' +
        'parameters. This takes a few seconds. The new environment starts ' +
        'completely empty — no locations, lines or boards — and the key ' +
        'cannot be changed afterwards because it forms the database name.'
      }
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={create} disabled={busy || !key || !name}>
            {busy ? 'Provisioning…' : 'Create'}
          </button>
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      <Field
        label="Key"
        hint="permanent"
        info="Lowercase letters, digits and underscores, starting with a letter. Becomes part of the database name, e.g. 'city1' gives 'its_city1'."
      >
        <input
          value={key}
          placeholder="city1"
          onChange={(e) => setKey(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
        />
      </Field>
      <Field label="Display name">
        <input
          value={name}
          placeholder="City One Transit"
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Notes" full>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
    </Modal>
  )
}

function DeleteButton({
  environment,
  onDone,
}: {
  environment: Environment
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [dropData, setDropData] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function remove() {
    setBusy(true)
    setError('')
    try {
      await api.del(`/environments/${environment.id}?drop_data=${dropData}`)
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
      <button className="small danger" onClick={() => setOpen(true)}>
        Delete
      </button>
      {open && (
        <Modal
          title={`Delete environment — ${environment.name}`}
          info="Unregistering leaves the database on disk, so the environment can be added back later. Dropping the database destroys every location, line, timetable, block and roster in it, and there is no undo."
          onClose={() => setOpen(false)}
          footer={
            <>
              <button onClick={() => setOpen(false)}>Cancel</button>
              <button
                className="danger"
                disabled={busy || (dropData && confirmText !== environment.key)}
                onClick={remove}
              >
                {busy ? 'Working…' : dropData ? 'Delete and destroy data' : 'Unregister'}
              </button>
            </>
          }
        >
          <Alert kind="err">{error}</Alert>
          <div className="field inline">
            <input
              type="checkbox"
              checked={dropData}
              onChange={(e) => {
                setDropData(e.target.checked)
                setConfirmText('')
              }}
            />
            <label>
              Also DROP the database <code>{environment.database_name}</code>
            </label>
          </div>
          {dropData && (
            <>
              <Alert kind="err">
                This destroys every location, line, timetable, block and roster
                in this environment. There is no undo, and no backup is taken.
              </Alert>
              <Field label={`Type the key "${environment.key}" to confirm`}>
                <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
              </Field>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
