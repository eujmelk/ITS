import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, getEnvironment, getToken, setEnvironment, setToken } from '../api/client'
import type { AppConfig, Environment, Role, User } from '../api/types'

interface AppState {
  user: User | null
  config: AppConfig | null
  /** Every environment this login can work in. */
  environments: Environment[]
  /** The one currently being worked in. */
  environment: Environment | null
  reloadEnvironments: () => Promise<void>
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
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [loading, setLoading] = useState(true)

  const reloadEnvironments = useCallback(async () => {
    try {
      const rows = await api.get<Environment[]>('/environments')
      setEnvironments(rows)
      // A stored key that no longer exists — the environment was deleted or
      // renamed away — would 404 every request. Fall back to the default.
      const stored = getEnvironment()
      if (stored && !rows.some((row) => row.key === stored)) {
        setEnvironment(null)
      }
    } catch {
      setEnvironments([])
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function boot() {
      try {
        const cfg = await api.get<AppConfig>('/config')
        if (!cancelled) {
          setConfig(cfg)
          // Keep the browser tab in step with the environment's name.
          if (cfg.app_name) document.title = cfg.app_name
        }
      } catch {
        /* the app still works without it; the map falls back to defaults */
      }
      if (getToken()) {
        try {
          const me = await api.get<User>('/auth/me')
          if (!cancelled) {
            setUser(me)
            await reloadEnvironments()
          }
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
  }, [reloadEnvironments])

  const login = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await api.login(username, password)
      setToken(access_token)
      setUser(await api.get<User>('/auth/me'))
      await reloadEnvironments()
    },
    [reloadEnvironments],
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    // The environment choice survives logout on purpose: signing back in
    // should land you where you were working.
  }, [])

  const value = useMemo<AppState>(() => {
    const hasRole = (...roles: Role[]) => !!user && roles.includes(user.role)
    const environment =
      environments.find((row) => row.is_current) ??
      environments.find((row) => row.is_default) ??
      environments[0] ??
      null
    return {
      user,
      config,
      environments,
      environment,
      reloadEnvironments,
      loading,
      login,
      logout,
      hasRole,
      canEdit: hasRole('admin', 'planner'),
      isAdmin: hasRole('admin'),
    }
  }, [user, config, environments, reloadEnvironments, loading, login, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>')
  return ctx
}
