'use client';

import { useState } from 'react';

export default function Admin() {
  const [token, setToken] = useState('');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');

  async function load() {
    setError('');
    const r = await fetch('/api/admin/stats', { headers: { 'x-admin-token': token } });
    const j = await r.json();
    if (!r.ok) return setError(j.error || 'Failed');
    setRows(j.speakers);
  }

  const total = rows?.reduce((a, r) => a + r.clips, 0) ?? 0;

  return (
    <main>
      <h1>Admin</h1>
      <p className="sub">Progress overview. Download audio with <code>npm run export</code> on your own machine.</p>
      {!rows && (
        <div className="card">
          <label>Admin token</label>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          {error && <p className="err">{error}</p>}
          <div className="row"><button className="primary" onClick={load}>Show</button></div>
        </div>
      )}
      {rows && (
        <div className="card">
          <p><b>{rows.length}</b> speakers, <b>{total}</b> clips</p>
          <table>
            <thead><tr><th>ID</th><th>Gender</th><th>Age</th><th>Region</th><th>Device</th><th>Clips</th><th>MB</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}><td>{r.id}</td><td>{r.gender}</td><td>{r.age_band}</td><td>{r.region}</td><td>{r.device}</td><td>{r.clips}</td><td>{(Number(r.bytes) / 1e6).toFixed(1)}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="row"><button onClick={load}>Refresh</button></div>
        </div>
      )}
    </main>
  );
}
