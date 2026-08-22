export const API = '/api/v1'

const TOKEN_KEY = 'transit.token'
const ENVIRONMENT_KEY = 'transit.environment'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/**
 * The environment (city) every request is scoped to.
 *
 * Sent as `X-Environment` on every call. Absent means "the default one", so a
 * fresh login and a plain curl both work. It is stored separately from the
 * token because one login reaches every environment.
 */
export function getEnvironment(): string | null {
  return localStorage.getItem(ENVIRONMENT_KEY)
}
export function setEnvironment(key: string | null) {
  if (key) localStorage.setItem(ENVIRONMENT_KEY, key)
  else localStorage.removeItem(ENVIRONMENT_KEY)
}

/**
 * Switch environment.
 *
 * A full reload, deliberately: every page's loaded rows, cached labels and
 * open editors belong to the city you are leaving. Reloading is the only
 * honest way to be sure none of it survives the switch.
 */
export function switchEnvironment(key: string) {
  setEnvironment(key)
  window.location.reload()
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * FastAPI reports validation problems as a list of per-field objects. Showing
 * the raw JSON is useless to a planner, so flatten it into readable lines.
 */
function describe(status: number, body: any): string {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p: any) => p !== 'body').join('.') : ''
        return field ? `${field}: ${d.msg}` : d.msg
      })
      .join('\n')
  }
  if (status === 401) return 'Your session has expired. Please log in again.'
  return `Request failed (${status})`
}

function authHeaders(existing?: HeadersInit): Headers {
  const headers = new Headers(existing)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const environment = getEnvironment()
  if (environment) headers.set('X-Environment', environment)
  return headers
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = authHeaders(init.headers)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const response = await fetch(`${API}${path}`, { ...init, headers })

  if (response.status === 401) {
    setToken(null)
    // Full reload rather than a router push: every cached page state now
    // belongs to a session that no longer exists.
    if (!location.pathname.startsWith('/login')) location.href = '/login'
    throw new ApiError(401, 'Session expired')
  }

  if (!response.ok) {
    let body: any = null
    try {
      body = await response.json()
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, describe(response.status, body))
  }

  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('Content-Type') || ''
  if (contentType.includes('application/json')) return (await response.json()) as T
  return (await response.blob()) as unknown as T
}

/**
 * Build a query string.
 *
 * Arrays repeat the key (`?pattern_id=3&pattern_id=4`), which is what FastAPI
 * expects for a `list[int]` parameter. `_repeated` takes explicit
 * `[key, value]` pairs for the same purpose when the caller has already built
 * them.
 */
function qs(params?: Record<string, any>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (key === '_repeated') {
      for (const [k, v] of (value ?? []) as [string, string][]) search.append(k, v)
      continue
    }
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === '') continue
        search.append(key, String(item))
      }
      continue
    }
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  get: <T>(path: string, params?: Record<string, any>) => request<T>(`${path}${qs(params)}`),
  post: <T>(path: string, body?: any, params?: Record<string, any>) =>
    request<T>(`${path}${qs(params)}`, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: any) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  put: <T>(path: string, body: any) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: 'DELETE' }),

  async login(username: string, password: string) {
    // The token endpoint is OAuth2 password flow, so form encoding, not JSON.
    const form = new URLSearchParams({ username, password })
    const response = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    })
    if (!response.ok) {
      let body: any = null
      try {
        body = await response.json()
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, describe(response.status, body))
    }
    return (await response.json()) as { access_token: string; expires_in: number }
  },

  /** Open a binary endpoint in a new tab, carrying the bearer token. */
  async openBlob(path: string, params?: Record<string, any>) {
    const blob = await request<Blob>(`${path}${qs(params)}`)
    const url = URL.createObjectURL(blob as Blob)
    window.open(url, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },

  /** Upload a file as multipart/form-data. */
  async upload<T>(path: string, file: File, params?: Record<string, any>): Promise<T> {
    const body = new FormData()
    body.append('file', file)
    // Deliberately no Content-Type: the browser must set it, because only it
    // knows the multipart boundary.
    const headers = authHeaders()
    const response = await fetch(`${API}${path}${qs(params)}`, {
      method: 'POST',
      headers,
      body,
    })
    if (!response.ok) {
      let payload: any = null
      try {
        payload = await response.json()
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(response.status, describe(response.status, payload))
    }
    return (await response.json()) as T
  },

  async downloadBlob(path: string, filename: string, params?: Record<string, any>) {
    const blob = await request<Blob>(`${path}${qs(params)}`)
    const url = URL.createObjectURL(blob as Blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}
