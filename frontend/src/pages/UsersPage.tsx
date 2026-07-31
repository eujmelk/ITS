import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { User } from '../api/types'
import { CrudTable } from '../components/Crud'
import { Alert, Field, Modal, PageHead, Panel } from '../components/ui'
import { useApp } from '../state/AppContext'

export default function UsersPage() {
  const { user } = useApp()
  const [pwOpen, setPwOpen] = useState(false)

  return (
    <>
      <PageHead
        title="Users"
        intro="Viewers can read everything and export. Planners can also change network, schedule, fare and block data. Administrators additionally manage users and operating parameters."
        actions={<button onClick={() => setPwOpen(true)}>Change my password</button>}
      />

      <Panel>
        <CrudTable<User>
          endpoint="/users"
          entityName="User"
          searchable={false}
          columns={[
            { key: 'username', label: 'Username' },
            { key: 'full_name', label: 'Name' },
            { key: 'email', label: 'Email' },
            {
              key: 'role',
              label: 'Role',
              render: (row) => <span className="tag">{row.role}</span>,
            },
            {
              key: 'is_active',
              label: 'Status',
              render: (row) =>
                row.is_active ? (
                  <span className="tag ok">active</span>
                ) : (
                  <span className="tag grey">disabled</span>
                ),
            },
          ]}
          fields={[
            { name: 'username', label: 'Username', required: true, only: 'create' },
            { name: 'full_name', label: 'Full name' },
            { name: 'email', label: 'Email' },
            {
              name: 'role',
              label: 'Role',
              type: 'select',
              required: true,
              options: [
                { value: 'viewer', label: 'viewer — read and export' },
                { value: 'planner', label: 'planner — edit planning data' },
                { value: 'admin', label: 'admin — everything' },
              ],
            },
            {
              name: 'password',
              label: 'Password',
              hint: 'at least 8 characters; leave blank on edit to keep it',
            },
            { name: 'is_active', label: 'Active', type: 'checkbox' },
          ]}
          defaults={{ role: 'viewer', is_active: true }}
          toPayload={(values, mode) => {
            const payload = { ...values }
            // A blank password on edit means "unchanged", not "clear it".
            if (mode === 'edit' && !payload.password) delete payload.password
            return payload
          }}
        />
        <p className="small muted">
          You cannot disable, demote or delete your own account, and the last
          administrator cannot be removed — that would lock everyone out of
          user management.
        </p>
      </Panel>

      {pwOpen && <PasswordModal onClose={() => setPwOpen(false)} username={user?.username} />}
    </>
  )
}

function PasswordModal({ onClose, username }: { onClose: () => void; username?: string }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function save() {
    if (next !== confirm) {
      setError('The two new passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.post('/auth/change-password', {
        current_password: current,
        new_password: next,
      })
      window.alert('Password updated.')
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`Change password — ${username ?? ''}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" onClick={save} disabled={busy || !current || next.length < 8}>
            {busy ? 'Saving…' : 'Change password'}
          </button>
        </>
      }
    >
      <Alert kind="err">{error}</Alert>
      <Field label="Current password">
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
      </Field>
      <Field label="New password" hint="at least 8 characters">
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      </Field>
      <Field label="Confirm new password">
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
      </Field>
    </Modal>
  )
}
