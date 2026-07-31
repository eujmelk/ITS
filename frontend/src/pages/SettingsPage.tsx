import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Parameter } from '../api/types'
import { Alert, Empty, PageHead, Panel, Spinner } from '../components/ui'
import { useApp } from '../state/AppContext'

export default function SettingsPage() {
  const { isAdmin } = useApp()
  const [rows, setRows] = useState<Parameter[]>([])
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const data = await api.get<Parameter[]>('/parameters')
      setRows(data)
      setDraft(Object.fromEntries(data.map((row) => [row.key, row.value])))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function save(key: string) {
    setError('')
    setSaved('')
    try {
      await api.patch(`/parameters/${key}`, { value: draft[key] })
      setSaved(key)
      await load()
      setTimeout(() => setSaved(''), 2500)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  async function restore() {
    setError('')
    try {
      await api.post('/parameters/reset-defaults')
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    }
  }

  return (
    <>
      <PageHead
        title="Settings"
        intro="Operating parameters the rule checks read. They are data, not configuration files — changing one takes effect immediately, with no redeploy."
        actions={
          isAdmin ? (
            <button onClick={restore} title="Re-insert any built-in parameter that was deleted">
              Restore missing defaults
            </button>
          ) : null
        }
      />

      <Panel>
        <Alert kind="err">{error}</Alert>
        {!isAdmin && (
          <Alert kind="info">
            You can see these values but only an administrator can change them.
          </Alert>
        )}
        {loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>No parameters found.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th style={{ width: 150 }}>Value</th>
                  <th>Unit</th>
                  <th>What it does</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td className="nowrap">
                      <code style={{ fontSize: 12 }}>{row.key}</code>
                    </td>
                    <td>
                      {row.value_type === 'bool' ? (
                        <select
                          value={String(draft[row.key])}
                          disabled={!isAdmin}
                          onChange={(e) => setDraft({ ...draft, [row.key]: e.target.value })}
                        >
                          <option value="true">true</option>
                          <option value="false">false</option>
                        </select>
                      ) : (
                        <input
                          value={draft[row.key] ?? ''}
                          disabled={!isAdmin}
                          type={row.value_type === 'string' ? 'text' : 'number'}
                          onChange={(e) => setDraft({ ...draft, [row.key]: e.target.value })}
                        />
                      )}
                    </td>
                    <td className="small muted">{row.unit}</td>
                    <td className="small">{row.description}</td>
                    <td className="actions">
                      {isAdmin && (
                        <button
                          className="small primary"
                          disabled={draft[row.key] === row.value}
                          onClick={() => save(row.key)}
                        >
                          {saved === row.key ? 'Saved' : 'Save'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Scope">
        <p className="small muted" style={{ marginTop: 0 }}>
          These are global: one rule set for the whole operation. Per-line or
          per-driver overrides are not implemented, but everything already
          reads parameters through a resolver that takes a scope argument, so
          adding an override table later needs no change to the checks
          themselves — and no change to this page beyond a scope selector.
        </p>
      </Panel>
    </>
  )
}
