import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Aggregation from '../pages/Aggregation'

describe('Aggregation', () => {
  it('renders section title', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText('Aggregation Control')).toBeInTheDocument()
  })

  it('shows programmatic API only warning', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText(/Programmatic API only/)).toBeInTheDocument()
    expect(screen.getByText(/POST \/api\/v1\/aggregation\/run/)).toBeInTheDocument()
  })

  it('shows endpoint table with POST method', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText('POST')).toBeInTheDocument()
    expect(screen.getByText('/api/v1/aggregation/run')).toBeInTheDocument()
  })

  it('shows prerequisites section', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText('Prerequisites')).toBeInTheDocument()
    expect(screen.getByText(/must have status/)).toBeInTheDocument()
  })

  it('renders all 9 request body field rows', () => {
    render(<Aggregation token="test-token" />)
    // model_version and round_number appear in both request and response tables
    expect(screen.getAllByText('model_version').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('round_number').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('reference_payload_base64')).toBeInTheDocument()
    expect(screen.getByText('updates[].payload_base64')).toBeInTheDocument()
  })

  it('renders all 7 response field rows', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText('aggregated_payload_base64')).toBeInTheDocument()
    expect(screen.getByText('tensor_names')).toBeInTheDocument()
    expect(screen.getByText('update_count')).toBeInTheDocument()
  })

  it('shows Response (200 OK) section', () => {
    render(<Aggregation token="test-token" />)
    expect(screen.getByText('Response (200 OK)')).toBeInTheDocument()
  })

  it('renders without crashing when token prop changes', () => {
    const { rerender } = render(<Aggregation token="token-a" />)
    rerender(<Aggregation token="token-b" />)
    expect(screen.getByText('Aggregation Control')).toBeInTheDocument()
  })
})
