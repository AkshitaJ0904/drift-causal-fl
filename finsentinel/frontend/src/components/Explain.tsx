import { useState, useRef, useEffect } from 'react'
import { GLOSSARY, type GlossaryKey } from '../glossary'

interface Props {
  term: GlossaryKey
  /** Override the display text shown in the tooltip (defaults to glossary short) */
  label?: string
}

/**
 * Info icon that shows a hover tooltip and a click popover with a full definition.
 * Uses the glossary as single source of truth.
 */
export default function Explain({ term, label }: Props) {
  const entry = GLOSSARY[term]
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (!entry) return null

  return (
    <span
      ref={ref}
      style={{ position: 'relative', display: 'inline-block', verticalAlign: 'middle', marginLeft: 4 }}
    >
      <button
        type="button"
        aria-label={`Explain: ${term}`}
        title={entry.short}
        onClick={() => setOpen(o => !o)}
        style={{
          width: 15, height: 15,
          borderRadius: '50%',
          border: '1px solid var(--border-strong)',
          background: 'var(--bg-hover)',
          color: 'var(--text-muted)',
          fontSize: 9,
          fontWeight: 700,
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          lineHeight: 1,
          padding: 0,
        }}
      >
        ?
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="false"
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 200,
            width: 300,
            background: 'var(--bg-card)',
            border: '1px solid var(--border-strong)',
            borderRadius: 'var(--radius)',
            boxShadow: 'var(--shadow-elevated)',
            padding: '12px 14px',
            marginTop: 4,
          }}
        >
          <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--text-primary)' }}>
            {label ?? term.replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.55, marginBottom: 8 }}>
            {entry.short}
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--text-muted)', lineHeight: 1.6, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            {entry.detail}
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={{
              marginTop: 10,
              fontSize: 11,
              color: 'var(--text-muted)',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
            }}
          >
            Close
          </button>
        </div>
      )}
    </span>
  )
}
