'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { SENTENCES } from '../lib/sentences';

const GROUP_LABEL = {
  casual: 'Everyday sentence',
  business: 'Phone / business sentence',
  numbers: 'Numbers: read each digit separately',
  codeswitch: 'Urdu with English words',
  free: 'Free speech: answer in your own words (10-20 seconds)',
};

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
const pickMime = () => (typeof MediaRecorder === 'undefined' ? '' : MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m)) || '');
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  del: (k) => { try { localStorage.removeItem(k); } catch {} },
};

// Each speaker gets their own fixed order (seeded by their code), so people who stop early
// cover different sentences instead of everyone covering the first few.
function orderFor(id) {
  let h = 2166136261;
  for (const c of id) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  const rand = () => {
    h = (h + 0x6d2b79f5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const a = [...SENTENCES];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default function Page() {
  const [stage, setStage] = useState('intro'); // intro | record | done
  const [speakerId, setSpeakerId] = useState(null);
  const [done, setDone] = useState([]);
  const [idx, setIdx] = useState(0);
  const [form, setForm] = useState({ consent: false, gender: '', age_band: '', region: '', mother_tongue: '', device: '', environment: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState('');
  const list = useMemo(() => (speakerId ? orderFor(speakerId) : SENTENCES), [speakerId]);

  // recording state
  const [recording, setRecording] = useState(false);
  const [clip, setClip] = useState(null); // { blob, url, ms, mime }
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const startRef = useRef(0);
  const streamRef = useRef(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  async function resume(id) {
    const r = await fetch(`/api/progress?speaker=${id}`);
    if (!r.ok) { store.del('speakerId'); return false; }
    store.set('speakerId', id);
    const { done: d } = await r.json();
    setSpeakerId(id);
    setDone(d);
    const next = orderFor(id).findIndex((s) => !d.includes(s.id));
    if (next === -1) setStage('done');
    else { setIdx(next); setStage('record'); }
    return true;
  }

  useEffect(() => {
    const id = store.get('speakerId');
    if (id) resume(id).catch(() => {});
  }, []);

  async function start() {
    setError('');
    if (!form.consent) return setError('Please tick the consent box.');
    if (!form.gender || !form.age_band || !form.region || !form.environment) return setError('Please fill in the required fields.');
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return setError('This browser cannot record audio. Try Chrome, or Safari on iPhone.');
    setBusy(true);
    try {
      const r = await fetch('/api/session', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(form) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || 'Could not start');
      store.set('speakerId', j.speakerId);
      setSpeakerId(j.speakerId);
      setDone([]);
      setIdx(0);
      setStage('record');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecord() {
    setError('');
    if (recording) { recRef.current?.stop(); return; }
    try {
      if (!streamRef.current) {
        streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: true } });
      }
      const mime = pickMime();
      const rec = new MediaRecorder(streamRef.current, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = () => {
        const ms = Date.now() - startRef.current;
        const type = rec.mimeType || mime || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type });
        setClip({ blob, url: URL.createObjectURL(blob), ms, mime: type });
        setRecording(false);
      };
      recRef.current = rec;
      if (clip) URL.revokeObjectURL(clip.url);
      setClip(null);
      startRef.current = Date.now();
      rec.start();
      setRecording(true);
    } catch {
      setError('Microphone access was blocked. Allow the microphone for this page and try again.');
    }
  }

  async function save() {
    const s = list[idx];
    if (clip.ms < 800) return setError('That was very short. Please record the whole sentence.');
    setBusy(true);
    setError('');
    try {
      const r = await fetch(`/api/clip?speaker=${speakerId}&sentence=${s.id}&duration=${clip.ms}`, {
        method: 'POST',
        headers: { 'content-type': clip.mime.split(';')[0] },
        body: clip.blob,
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || 'Upload failed');
      const d = done.includes(s.id) ? done : [...done, s.id];
      setDone(d);
      URL.revokeObjectURL(clip.url);
      setClip(null);
      let next = list.findIndex((x, i) => i > idx && !d.includes(x.id));
      if (next === -1) next = list.findIndex((x) => !d.includes(x.id));
      if (next === -1) { setStage('done'); store.del('speakerId'); }
      else setIdx(next);
    } catch (e) {
      setError(e.message + ' (your recording is still here, press Save again)');
    } finally {
      setBusy(false);
    }
  }

  if (stage === 'done') {
    return (
      <main>
        <div className="card">
          <h1>Thank you!</h1>
          <p className="sub">All your recordings are saved. You can close this page.</p>
        </div>
      </main>
    );
  }

  if (stage === 'record') {
    const s = list[idx];
    const pct = Math.round((done.length / list.length) * 100);
    return (
      <main>
        <h1>Sentence {idx + 1} of {list.length}</h1>
        <div className="bar"><div style={{ width: `${pct}%` }} /></div>
        <div className="card">
          <span className="tag">{GROUP_LABEL[s.group]}</span>
          <p className="urdu">{s.text}</p>
          <p className="hint">Press Record, read the sentence naturally at your normal pace, then press Stop. You can listen and re-record before saving.</p>
          <div className="row">
            <button className={recording ? '' : 'rec'} onClick={toggleRecord} disabled={busy}>
              {recording ? <><span className="dot" />Stop</> : clip ? 'Record again' : 'Record'}
            </button>
            {clip && !recording && <button className="primary" onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save and next'}</button>}
          </div>
          {clip && !recording && <audio controls src={clip.url} />}
          {error && <p className="err">{error}</p>}
        </div>
        <div className="row">
          <button onClick={() => { setClip(null); setIdx((i) => Math.max(0, i - 1)); }} disabled={idx === 0 || recording || busy}>Back</button>
          <button onClick={() => { setClip(null); setIdx((i) => Math.min(list.length - 1, i + 1)); }} disabled={idx === list.length - 1 || recording || busy}>Skip</button>
        </div>
        <p className="hint">Tip: use a quiet room and keep the phone about a hand-span from your mouth. Every sentence is saved as soon as you press Save, so you can stop any time. To continue later (even on another device), open this page again and enter your code: <b>{speakerId}</b>. Sentences you already recorded are skipped.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Urdu Voice Recorder</h1>
      <p className="sub">We are testing Urdu speech software and need real native speakers. It takes about 10-15 minutes.</p>
      <div className="card">
        <h2>About you</h2>
        <p className="hint">No name, phone number or email is collected.</p>
        <label>Gender *</label>
        <select value={form.gender} onChange={set('gender')}>
          <option value="">Select…</option><option>Female</option><option>Male</option><option>Prefer not to say</option>
        </select>
        <label>Age group *</label>
        <select value={form.age_band} onChange={set('age_band')}>
          <option value="">Select…</option><option>Under 18</option><option>18-24</option><option>25-34</option><option>35-49</option><option>50+</option>
        </select>
        <label>Where did you grow up? (city / province) *</label>
        <input type="text" value={form.region} onChange={set('region')} />
        <label>Mother tongue</label>
        <input type="text" value={form.mother_tongue} onChange={set('mother_tongue')} placeholder="e.g. Urdu, Punjabi, Pashto" />
        <label>Recording device</label>
        <select value={form.device} onChange={set('device')}>
          <option value="">Select…</option><option>Phone</option><option>Laptop</option><option>Headset or external mic</option>
        </select>
        <label>Where are you recording? *</label>
        <select value={form.environment} onChange={set('environment')}>
          <option value="">Select…</option><option>Quiet room</option><option>Some background noise</option><option>Noisy place</option>
        </select>
        <label className="check">
          <input type="checkbox" checked={form.consent} onChange={set('consent')} />
          <span>I agree that my voice recordings and the answers above may be stored and used by this university project to test speech software, and may be shared only inside the project team. I can ask to have my recordings deleted at any time by contacting the project team.</span>
        </label>
        {error && <p className="err">{error}</p>}
        <div className="row"><button className="primary" onClick={start} disabled={busy}>{busy ? 'Starting…' : 'Start recording'}</button></div>
      </div>
      <div className="card">
        <h2>Already started?</h2>
        <p className="hint">Enter the code shown at the bottom of the recording page to continue where you stopped.</p>
        <input type="text" value={code} onChange={(e) => setCode(e.target.value.trim())} placeholder="e.g. 0565e8b8" autoCapitalize="off" />
        <div className="row">
          <button disabled={!code || busy} onClick={async () => { setError(''); setBusy(true); const ok = await resume(code).catch(() => false); setBusy(false); if (!ok) setError('Code not found.'); }}>Continue</button>
        </div>
      </div>
    </main>
  );
}
