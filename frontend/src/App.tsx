import { useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { switchEnvironment } from './api/client'
import { useApp } from './state/AppContext'
import EnvironmentsPage from './pages/EnvironmentsPage'
import { AboutDialog, MenuBar, StatusBar, TabStrip, useGo } from './components/Chrome'
import type { MenuDef, TabDef } from './components/Chrome'
import LoginPage from './pages/LoginPage'
import LocationsPage from './pages/LocationsPage'
import LinesPage from './pages/LinesPage'
import BoardsPage from './pages/BoardsPage'
import SchedulePage from './pages/SchedulePage'
import FaresPage from './pages/FaresPage'
import FleetPage from './pages/FleetPage'
import RosterPage from './pages/RosterPage'
import SettingsPage from './pages/SettingsPage'
import ItineraryPage from './pages/ItineraryPage'
import UsersPage from './pages/UsersPage'

const TABS: TabDef[] = [
  { to: '/locations', label: 'Locations' },
  { to: '/lines', label: 'Lines' },
  { to: '/boards', label: 'Boards' },
  { to: '/schedule', label: 'Timetables' },
  { to: '/fares', label: 'Fares' },
  { to: '/fleet', label: 'Fleet' },
  { to: '/roster', label: 'Roster' },
  { to: '/itinerary', label: 'Itinerary' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  const { user, loading, logout, isAdmin, config, environments, environment } = useApp()
  const go = useGo()
  const location = useLocation()
  const [aboutOpen, setAboutOpen] = useState(false)

  if (loading) {
    return <div className="empty" style={{ marginTop: 60 }}>Starting…</div>
  }
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  const tabs: TabDef[] = [...TABS, { to: '/users', label: 'Users', hidden: !isAdmin }]

  // Every entry here goes somewhere that already exists; the menu bar is
  // navigation and session control, not a second set of features.
  const menus: MenuDef[] = [
    {
      title: 'File',
      items: [
        { label: 'Change password…', onSelect: () => go('/users') },
        { separator: true, label: 'sep-1' },
        { label: 'Log out', onSelect: logout },
      ],
    },
    {
      title: 'View',
      items: tabs
        .filter((tab) => !tab.hidden)
        .map((tab) => ({
          label: tab.label,
          checked: location.pathname === tab.to,
          onSelect: () => go(tab.to),
        })),
    },
    {
      // The switcher the user asked for: pick a city, the app reloads into it.
      title: 'Environments',
      items: [
        ...environments.map((row) => ({
          label: row.name,
          accel: row.key,
          checked: row.key === environment?.key,
          onSelect: () => {
            if (row.key !== environment?.key) switchEnvironment(row.key)
          },
        })),
        { separator: true, label: 'sep-env' },
        {
          label: 'Manage environments…',
          hidden: !isAdmin,
          onSelect: () => go('/environments'),
        },
      ],
    },
    {
      title: 'Tools',
      items: [
        { label: 'Operating parameters…', onSelect: () => go('/settings') },
        { label: 'Users…', hidden: !isAdmin, onSelect: () => go('/users') },
        { separator: true, label: 'sep-2' },
        { label: 'Itinerary finder…', onSelect: () => go('/itinerary') },
      ],
    },
    {
      title: 'Help',
      items: [{ label: 'About…', onSelect: () => setAboutOpen(true) }],
    },
  ]

  return (
    <div className="app">
      <MenuBar menus={menus} />
      <TabStrip tabs={tabs} />

      <div className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/locations" replace />} />
          <Route path="/login" element={<Navigate to="/locations" replace />} />
          <Route path="/locations" element={<LocationsPage />} />
          <Route path="/lines" element={<LinesPage />} />
          <Route path="/boards" element={<BoardsPage />} />
          <Route path="/schedule" element={<SchedulePage />} />
          <Route path="/fares" element={<FaresPage />} />
          <Route path="/fleet" element={<FleetPage />} />
          <Route path="/roster" element={<RosterPage />} />
          <Route path="/itinerary" element={<ItineraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          {isAdmin && <Route path="/users" element={<UsersPage />} />}
          {isAdmin && <Route path="/environments" element={<EnvironmentsPage />} />}
          <Route path="*" element={<div className="empty">Page not found.</div>} />
        </Routes>
      </div>

      <StatusBar
        right={
          <>
            {/* Which city you are in belongs where you can always see it: an
                edit made in the wrong environment is expensive to undo. */}
            <strong>{environment?.name ?? config?.app_name ?? 'Transit'}</strong>
            <span className="muted">|</span>
            <span>
              {user.full_name || user.username} ({user.role})
            </span>
          </>
        }
      />

      {aboutOpen && <AboutDialog onClose={() => setAboutOpen(false)} />}
    </div>
  )
}
