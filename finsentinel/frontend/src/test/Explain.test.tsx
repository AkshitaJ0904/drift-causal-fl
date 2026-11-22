import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Explain from '../components/Explain'
import { GLOSSARY } from '../glossary'

describe('Explain component', () => {
  it('renders an info button', () => {
    render(<Explain term="severity" />)
    expect(screen.getByRole('button', { name: /Explain: severity/i })).toBeInTheDocument()
  })

  it('popover is not visible before click', () => {
    render(<Explain term="severity" />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('popover opens on click', () => {
    render(<Explain term="severity" />)
    fireEvent.click(screen.getByRole('button', { name: /Explain: severity/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('popover shows short and detail text', () => {
    render(<Explain term="severity" />)
    fireEvent.click(screen.getByRole('button', { name: /Explain: severity/i }))
    expect(screen.getByText(GLOSSARY.severity.short)).toBeInTheDocument()
  })

  it('popover closes on Close button click', () => {
    render(<Explain term="severity" />)
    fireEvent.click(screen.getByRole('button', { name: /Explain: severity/i }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Close/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders nothing for an unknown term', () => {
    const { container } = render(<Explain term={"unknown_xyz" as never} />)
    expect(container.firstChild).toBeNull()
  })
})

describe('Glossary coverage', () => {
  const REQUIRED_TERMS = [
    'client_id', 'anomaly_score', 'l2_norm', 'signature', 'sha256',
    'replay', 'nonce', 'schema', 'quarantine', 'dead_letter',
    'outbox', 'severity', 'mitre',
  ] as const

  it.each(REQUIRED_TERMS)('glossary defines "%s"', (term) => {
    expect(GLOSSARY[term]).toBeDefined()
    expect(GLOSSARY[term].short.length).toBeGreaterThan(10)
    expect(GLOSSARY[term].detail.length).toBeGreaterThan(20)
  })
})
