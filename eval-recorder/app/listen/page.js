'use client';

import { useEffect, useRef, useState } from 'react';

const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  del: (k) => { try { localStorage.removeItem(k); } catch {} },
};

const SCALE_MOS = ['Bad', 'Poor', 'Fair', 'Good', 'Excellent'];
const SCALE_ACCENT = ['Not Pakistani at all', 'Slightly', 'Somewhat', 'Mostly', 'Completely natural Pakistani'];

function Player({ id, label, onHeard }) {
  return (
    <div style={{ marginTop: 12 }}>
      {label && <b>{label}</b>}
      <audio controls controlsList="nodownload" preload="auto" src={`/api/listen/audio?id=${id}`} onEnded={onHeard} />
    </div>
  );
}

function Trial({ trial, onAnswer, busy }) {
  const [heardA, setHeardA] = useState(false);
  const [heardB, setHeardB] = useState(false);
  const t0 = useRef(Date.now());
  useEffect(() => { setHeardA(false); setHeardB(false); t0.current = Date.now(); }, [trial.idx]);
  const ready = trial.kind === 'ab' ? heardA && heardB : heardA;
  const ms = () => Date.now() - t0.current;

  if (trial.kind === 'ab') {
    return (
      <div className="card" key={trial.idx}>
        <h2>Which one sounds better?</h2>
        <p className="hint">Two recordings of the same sentence. Listen to both all the way through, then choose.</p>
        <Player id={trial.a} label="Recording A" onHeard={() => setHeardA(true)} />
        <Player id={trial.b} label="Recording B" onHeard={() => setHeardB(true)} />
        <div className="row">
          <button disabled={!ready || busy} onClick={() => onAnswer({ choice: 'A', listen_ms: ms() })}>A is better</button>
          <button disabled={!ready || busy} onClick={() => onAnswer({ choice: 'same', listen_ms: ms() })}>About the same</button>
          <button disabled={!ready || busy} onClick={() => onAnswer({ choice: 'B', listen_ms: ms() })}>B is better</button>
        </div>
      </div>
    );
  }

  const accent = trial.kind === 'accent';
  const scale = accent ? SCALE_ACCENT : SCALE_MOS;
  return (
    <div className="card" key={trial.idx}>
      <h2>{accent ? 'How native does this speaker sound?' : 'How natural does this sound?'}</h2>
      <p className="hint">
        {accent
          ? 'Does the accent sound like a native speaker from Pakistan?'
          : 'Rate how natural and pleasant this is, as if a person were speaking Urdu to you. Ignore the volume.'}
      </p>
      <Player id={trial.a} onHeard={() => setHeardA(true)} />
      <div className="row">
        {scale.map((label, i) => (
          <button key={i} disabled={!ready || busy} onClick={() => onAnswer({ score: i + 1, listen_ms: ms() })}>
            {i + 1}<br /><small>{label}</small>
          </button>
        ))}
      </div>
      {!ready && <p className="hint">Listen to the whole clip to enable the buttons.</p>}
    </div>
  );
}

export default function Listen() {
  const [stage, setStage] = useState('intro'); // intro | test | done
  const [raterId, setRaterId] = useState(null);
  const [trials, setTrials] = useState([]);
  const [done, setDone] = useState([]);
  const [form, setForm] = useState({ consent: false, native: '', age_band: '', region: '', gender: '', listening_device: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  async function load(id) {
    const r = await fetch(`/api/listen/plan?rater=${id}`);
    if (!r.ok) { store.del('raterId'); return false; }
    const j = await r.json();
    setRaterId(id); setTrials(j.trials); setDone(j.done);
    setStage(j.done.length >= j.trials.length ? 'done' : 'test');
    return true;
  }
  useEffect(() => { const id = store.get('raterId'); if (id) load(id).catch(() => {}); }, []);

  async function start() {
    setError('');
    if (!form.consent) return setError('Please tick the consent box.');
    if (!form.native || !form.age_band || !form.listening_device) return setError('Please fill in the required fields.');
    setBusy(true);
    try {
      const r = await fetch('/api/listen/session', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(form) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not start');
      store.set('raterId', j.raterId);
      await load(j.raterId);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  async function answer(a) {
    const idx = trials.find((t) => !done.includes(t.idx)).idx;
    setBusy(true); setError('');
    try {
      const r = await fetch('/api/listen/rate', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ rater: raterId, idx, ...a }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Could not save');
      const d = [...done, idx];
      setDone(d);
      if (d.length >= trials.length) { setStage('done'); store.del('raterId'); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  if (stage === 'done') {
    return <main><div className="card"><h1>Thank you!</h1><p className="sub">Your ratings are saved. You can close this page.</p></div></main>;
  }

  if (stage === 'test') {
    const current = trials.find((t) => !done.includes(t.idx));
    const pct = Math.round((done.length / trials.length) * 100);
    return (
      <main>
        <h1>Clip {done.length + 1} of {trials.length}</h1>
        <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        {current && <Trial trial={current} onAnswer={answer} busy={busy} />}
        {error && <p className="err">{error}</p>}
        <p className="hint">Your answers are saved after every clip. To continue later on this device, just open this page again.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Urdu Voice Listening Test</h1>
      <p className="sub">You will hear short Urdu sentences, some by people and some by computer voices, and rate them. It takes about 10 minutes. Please use headphones in a quiet place.</p>
      <div className="card">
        <h2>About you</h2>
        <p className="hint">No name, phone number or email is collected.</p>
        <label>Is Urdu your first language? *</label>
        <select value={form.native} onChange={set('native')}>
          <option value="">Select…</option><option>Yes</option><option>No, but I speak it fluently</option><option>No</option>
        </select>
        <label>Age group *</label>
        <select value={form.age_band} onChange={set('age_band')}>
          <option value="">Select…</option><option>Under 18</option><option>18-24</option><option>25-34</option><option>35-49</option><option>50+</option>
        </select>
        <label>Where did you grow up? (city / province)</label>
        <input type="text" value={form.region} onChange={set('region')} />
        <label>Gender</label>
        <select value={form.gender} onChange={set('gender')}>
          <option value="">Select…</option><option>Female</option><option>Male</option><option>Prefer not to say</option>
        </select>
        <label>What are you listening with? *</label>
        <select value={form.listening_device} onChange={set('listening_device')}>
          <option value="">Select…</option><option>Headphones</option><option>Earbuds</option><option>Laptop speakers</option><option>Phone speaker</option>
        </select>
        <label className="check">
          <input type="checkbox" checked={form.consent} onChange={set('consent')} />
          <span>I agree that my ratings and the answers above may be stored and used by this university project to evaluate speech software. I understand some recordings are of real people who agreed to take part.</span>
        </label>
        {error && <p className="err">{error}</p>}
        <div className="row"><button className="primary" onClick={start} disabled={busy}>{busy ? 'Starting…' : 'Start'}</button></div>
      </div>
    </main>
  );
}
