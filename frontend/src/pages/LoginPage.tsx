import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useApp } from '../state/AppContext'
import { Alert } from '../components/ui'

export default function LoginPage() {
  const { login, config } = useApp()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(username, password)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <header>{config?.app_name ?? 'Transit Scheduling'} — Log On</header>
        <div className="body">
          <Alert kind="err">{error}</Alert>
          <div className="field">
            <label>User name:</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <label>Password:</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 5, marginTop: 8 }}>
            <button className="primary" disabled={busy} style={{ minWidth: 72 }}>
              {busy ? 'Working…' : 'OK'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
