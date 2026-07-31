import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useApp } from './state/AppContext'
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

const NAV = [
  { group: 'Network', items: [
    { to: '/locations', label: 'Locations' },
    { to: '/lines', label: 'Lines & patterns' },
  ]},
  { group: 'Service', items: [
    { to: '/boards', label: 'Schedule boards' },
    { to: '/schedule', label: 'Timetables' },
    { to: '/fares', label: 'Fares' },
  ]},
  { group: 'Operations', items: [
    { to: '/fleet', label: 'Fleet & blocks' },
    { to: '/roster', label: 'Roster' },
  ]},
  { group: 'Tools', items: [
    { to: '/itinerary', label: 'Itinerary finder' },
    { to: '/settings', label: 'Settings' },
    { to: '/users', label: 'Users', adminOnly: true },
  ]},
]

export default function App() {
  const { user, loading, logout, isAdmin, config } = useApp()

  if (loading) return <div className="empty" style={{ marginTop: 80 }}>Starting…</div>
  if (!user) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1>{config?.app_name ?? 'Transit Scheduling'}</h1>
        <nav>
          {NAV.map((section) => (
            <div key={section.group}>
              <div className="group">{section.group}</div>
              {section.items
                .filter((item) => !item.adminOnly || isAdmin)
                .map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) => (isActive ? 'active' : '')}
                  >
                    {item.label}
                  </NavLink>
                ))}
            </div>
          ))}
        </nav>
        <div className="foot">
          <div>{user.full_name || user.username}</div>
          <div className="muted" style={{ color: '#a8c4da' }}>{user.role}</div>
          <button onClick={logout}>Log out</button>
        </div>
      </aside>

      <main className="main">
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
          <Route path="*" element={<div className="empty">Page not found.</div>} />
        </Routes>
      </main>
    </div>
  )
}
