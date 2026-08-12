import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useApp } from '../state/AppContext'
import { useStatus } from '../state/StatusContext'

/* ---------------------------------------------------------------- menus --- */

export interface MenuItem {
  label: string
  accel?: string
  onSelect?: () => void
  separator?: boolean
  hidden?: boolean
  checked?: boolean
}

export interface MenuDef {
  title: string
  items: MenuItem[]
}

/**
 * Classic menu bar.
 *
 * Only ever navigates or triggers something the application already does —
 * no menu entry here adds a capability that was not already reachable.
 * Once a menu is open, hovering the siblings switches between them, which is
 * the behaviour every desktop menu bar has had since 1995.
 */
export function MenuBar({ menus }: { menus: MenuDef[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const barRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(event: MouseEvent) {
      if (!barRef.current?.contains(event.target as Node)) setOpen(null)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(null)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="menubar" ref={barRef}>
      {menus.map((menu) => (
        <div className="menu" key={menu.title}>
          <div
            className={`menu-title${open === menu.title ? ' open' : ''}`}
            onClick={() => setOpen(open === menu.title ? null : menu.title)}
            onMouseEnter={() => open && setOpen(menu.title)}
          >
            {menu.title}
          </div>
          {open === menu.title && (
            <div className="menu-drop">
              {menu.items
                .filter((item) => !item.hidden)
                .map((item, index) =>
                  item.separator ? (
                    <div className="menu-sep" key={`sep-${index}`} />
                  ) : (
                    <div
                      className={`menu-item${item.checked ? ' checked' : ''}`}
                      key={item.label}
                      onClick={() => {
                        setOpen(null)
                        item.onSelect?.()
                      }}
                    >
                      <span>{item.label}</span>
                      {item.accel && <span className="accel">{item.accel}</span>}
                    </div>
                  ),
                )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------ tab strip --- */

export interface TabDef {
  to: string
  label: string
  hidden?: boolean
}

export function TabStrip({ tabs }: { tabs: TabDef[] }) {
  return (
    <div className="tabstrip">
      {tabs
        .filter((tab) => !tab.hidden)
        .map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) => `tab${isActive ? ' active' : ''}`}
          >
            {tab.label}
          </NavLink>
        ))}
    </div>
  )
}

/* ----------------------------------------------------------- status bar --- */

export function StatusBar({ right }: { right?: ReactNode }) {
  const { message, clear } = useStatus()

  return (
    <div className="statusbar">
      <div className="panel-cell grow">
        {message ? (
          <>
            <button className="small" onClick={clear} title="Clear this message">
              ×
            </button>
            <span className="msg long">{message}</span>
          </>
        ) : (
          <span className="msg muted">
            Ready — click any (i) for an explanation of the section next to it.
          </span>
        )}
      </div>
      {right && <div className="panel-cell">{right}</div>}
    </div>
  )
}

/* ---------------------------------------------------------------- about --- */

export function AboutDialog({ onClose }: { onClose: () => void }) {
  const { config, user } = useApp()
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 340 }}>
        <header>
          <span>About</span>
          <button onClick={onClose}>×</button>
        </header>
        <div className="body">
          <p style={{ marginTop: 0 }}>
            <strong>{config?.app_name ?? 'Transit Scheduling'}</strong>
            <br />
            Version 1.0.0
          </p>
          <p className="small muted">
            Signed in as {user?.full_name || user?.username} ({user?.role}).
          </p>
        </div>
        <footer>
          <button className="primary" onClick={onClose}>
            OK
          </button>
        </footer>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- navigate --- */

/** Convenience for menu items that only need to change page. */
export function useGo() {
  const navigate = useNavigate()
  return (to: string) => navigate(to)
}
