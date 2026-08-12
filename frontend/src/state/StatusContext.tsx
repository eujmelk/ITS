import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * The status bar, and the (i) buttons that feed it.
 *
 * All explanatory prose lives here rather than under headings. On screens
 * carrying a few hundred timetable rows, a paragraph of help above the grid
 * costs more than it gives — so the text is one click away in the status bar,
 * where it never displaces data and never needs a hover.
 *
 * One message at a time, VB6 style. Clicking another (i) replaces it.
 */

interface StatusState {
  message: ReactNode | null
  /** Show text in the status bar. Passing the same text again clears it. */
  show: (text: ReactNode, key: string) => void
  clear: () => void
  activeKey: string | null
}

const Ctx = createContext<StatusState | null>(null)

export function StatusProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<ReactNode | null>(null)
  const [activeKey, setActiveKey] = useState<string | null>(null)

  const show = useCallback((text: ReactNode, key: string) => {
    // Clicking the same (i) again is how you dismiss it; a second control to
    // close would be one more thing on screen.
    setActiveKey((current) => {
      if (current === key) {
        setMessage(null)
        return null
      }
      setMessage(text)
      return key
    })
  }, [])

  const clear = useCallback(() => {
    setMessage(null)
    setActiveKey(null)
  }, [])

  const value = useMemo(
    () => ({ message, show, clear, activeKey }),
    [message, show, clear, activeKey],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStatus(): StatusState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useStatus must be used inside <StatusProvider>')
  return ctx
}

let counter = 0

/**
 * The (i) button. Put one next to any title or subtitle that needs
 * explaining; its text goes to the status bar on click.
 */
export function Info({ children }: { children: ReactNode }) {
  const { show, activeKey } = useStatus()
  // A stable identity per mounted button, so the toggle knows which is open.
  const [key] = useState(() => `info-${(counter += 1)}`)
  const open = activeKey === key

  return (
    <button
      type="button"
      className="info-btn"
      aria-label="Show help for this section"
      aria-pressed={open}
      title="What is this?"
      onClick={(event) => {
        event.stopPropagation()
        show(children, key)
      }}
    >
      i
    </button>
  )
}
