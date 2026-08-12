import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, getToken, setToken } from '../api/client'
import type { AppConfig, Role, User } from '../api/types'

interface AppState {
  user: User | null
  config: AppConfig | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  /** True when the current user may change planning data. */
  canEdit: boolean
  isAdmin: boolean
  hasRole: (...roles: Role[]) => boolean
}

const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function boot() {
      try {
        const cfg = await api.get<AppConfig>('/config')
        if (!cancelled) {
          setConfig(cfg)
          // Keep the browser tab in step with the configured instance name.
          if (cfg.app_name) document.title = cfg.app_name
        }
      } catch {
        /* the app still works without it; the map falls back to defaults */
      }
      if (getToken()) {
        try {
          const me = await api.get<User>('/auth/me')
          if (!cancelled) setUser(me)
        } catch {
          setToken(null)
        }
      }
      if (!cancelled) setLoading(false)
    }
    boot()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await api.login(username, password)
    setToken(access_token)
    setUser(await api.get<User>('/auth/me'))
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo<AppState>(() => {
    const hasRole = (...roles: Role[]) => !!user && roles.includes(user.role)
    return {
      user,
      config,
      loading,
      login,
      logout,
      hasRole,
      canEdit: hasRole('admin', 'planner'),
      isAdmin: hasRole('admin'),
    }
  }, [user, config, loading, login, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>')
  return ctx
}
