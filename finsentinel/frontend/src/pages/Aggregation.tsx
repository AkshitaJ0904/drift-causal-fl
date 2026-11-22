interface Props {
  token: string
}

const FIELD_ROWS = [
  { field: 'model_version',            type: 'string',       note: "Semantic version matching the registered model schema." },
  { field: 'round_number',             type: 'integer ≥ 1',  note: "The FL training round being aggregated." },
  { field: 'reference_payload_base64', type: 'string',       note: "Base64-encoded NPZ bytes of the server's current trusted model weights." },
  { field: 'updates[].client_id',      type: 'string',       note: "Client identifier (must match approval registry entry)." },
  { field: 'updates[].update_id',      type: 'string',       note: "Update identifier (must match approval registry entry)." },
  { field: 'updates[].model_version',  type: 'string',       note: "Must match the top-level model_version." },
  { field: 'updates[].round_number',   type: 'integer ≥ 1',  note: "Must match the top-level round_number." },
  { field: 'updates[].sample_count',   type: 'integer > 0',  note: "Training-sample count used to weight the update." },
  { field: 'updates[].payload_base64', type: 'string',       note: "Base64-encoded NPZ bytes of the client's weight update." },
]

const RESPONSE_ROWS = [
  { field: 'model_version',             type: 'string',   note: 'Echoed from request.' },
  { field: 'round_number',              type: 'integer',  note: 'Echoed from request.' },
  { field: 'update_count',              type: 'integer',  note: 'Number of updates included in aggregation.' },
  { field: 'total_samples',             type: 'integer',  note: 'Sum of sample counts across all included updates.' },
  { field: 'tensor_count',              type: 'integer',  note: 'Number of tensors in the aggregated model.' },
  { field: 'tensor_names',              type: 'string[]', note: 'Names of aggregated tensors.' },
  { field: 'aggregated_payload_base64', type: 'string',   note: 'Base64-encoded NPZ bytes of the aggregated model. Store as the new global model.' },
]

export default function Aggregation(_props: Props) {
  return (
    <div>
      <div className="section-header">
        <div>
          <div className="section-title">Aggregation Control</div>
          <div className="section-desc">
            Combines approved client updates into a new global model using federated averaging. Requires full NPZ-encoded payloads — call this endpoint from the FL coordinator, not from a browser.
          </div>
        </div>
      </div>

      <div className="alert alert-warn mb-16">
        <strong>Programmatic API only.</strong> POST /api/v1/aggregation/run requires
        full NPZ-encoded model payloads that cannot be constructed in a browser form.
        Call this endpoint from the FL coordinator or a trusted automation script.
      </div>

      {/* Endpoint */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Endpoint</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Method</th><th>Path</th><th>Auth</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><span className="badge badge-cyan">POST</span></td>
              <td className="mono">/api/v1/aggregation/run</td>
              <td><span className="badge badge-blue">operator bearer token</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Prerequisites */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Prerequisites</span>
        </div>
        <ol style={{ paddingLeft: 20, lineHeight: 2, color: 'var(--text-secondary)', fontSize: 13, margin: 0 }}>
          <li>All included updates must have status <span className="badge badge-green mono">approved</span> in the approval registry.</li>
          <li>Client payloads must be encoded as NumPy NPZ archives (<span className="mono">.npz</span>) and Base64-encoded.</li>
          <li>The reference payload must be the server's current global model, also NPZ-encoded and Base64-encoded.</li>
          <li>
            Model version and round number must match the registered schema.
            Mismatches return <span className="mono">422 Unprocessable Entity</span>.
          </li>
        </ol>
      </div>

      {/* Request body */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Request Body Fields</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Field</th><th>Type</th><th>Description</th></tr>
          </thead>
          <tbody>
            {FIELD_ROWS.map((row) => (
              <tr key={row.field}>
                <td className="mono">{row.field}</td>
                <td className="mono text-muted">{row.type}</td>
                <td className="text-muted">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Response */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Response (200 OK)</span>
        </div>
        <table className="data-table">
          <thead>
            <tr><th>Field</th><th>Type</th><th>Description</th></tr>
          </thead>
          <tbody>
            {RESPONSE_ROWS.map((row) => (
              <tr key={row.field}>
                <td className="mono">{row.field}</td>
                <td className="mono text-muted">{row.type}</td>
                <td className="text-muted">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
