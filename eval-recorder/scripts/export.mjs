// Download every clip from the database into exports/, convert to 16 kHz mono WAV if ffmpeg exists,
// and write metadata.csv + sentences.tsv. Run: npm run export   (reads .env.local)
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import pg from 'pg';
import { SENTENCES } from '../lib/sentences.js';

function loadEnv(path) {
  try {
    for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^([A-Z_]+)=(.*)$/);
      if (m && !(m[1] in process.env)) process.env[m[1]] = m[2];
    }
  } catch {}
}
loadEnv(new URL('../.env.local', import.meta.url));

const url = process.env.AIVEN_DATABASE_URL;
if (!url) throw new Error('AIVEN_DATABASE_URL missing');
const ca = process.env.AIVEN_CA_CERT;
const pool = new pg.Pool({
  connectionString: url.replace(/[?&]sslmode=[^&]*/g, '').replace(/\?$/, ''),
  ssl: ca ? { ca } : { rejectUnauthorized: false },
});

const ext = (mime) => (mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : 'webm');
const hasFfmpeg = spawnSync('ffmpeg', ['-version']).status === 0;
if (!hasFfmpeg) console.warn('ffmpeg not found: keeping original files only (install ffmpeg to get 16 kHz WAV).');

const out = new URL('../exports/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
mkdirSync(join(out, 'raw'), { recursive: true });
mkdirSync(join(out, 'wav'), { recursive: true });

const speakers = (await pool.query('SELECT * FROM evalrec.speakers ORDER BY created_at')).rows;
const recs = (await pool.query('SELECT id, speaker_id, sentence_id, mime, duration_ms, audio FROM evalrec.recordings ORDER BY id')).rows;

const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
const lines = ['speaker_id,sentence_id,group,duration_ms,raw_file,wav_file,gender,age_band,region,mother_tongue,device,environment'];
const sp = Object.fromEntries(speakers.map((s) => [s.id, s]));
const grp = Object.fromEntries(SENTENCES.map((s) => [s.id, s.group]));

for (const r of recs) {
  const name = `${r.speaker_id}_${r.sentence_id}`;
  const rawRel = `raw/${name}.${ext(r.mime)}`;
  writeFileSync(join(out, rawRel), r.audio);
  let wavRel = '';
  if (hasFfmpeg) {
    wavRel = `wav/${name}.wav`;
    const p = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', join(out, rawRel), '-ac', '1', '-ar', '16000', join(out, wavRel)]);
    if (p.status !== 0) wavRel = '';
  }
  const s = sp[r.speaker_id] || {};
  lines.push([r.speaker_id, r.sentence_id, grp[r.sentence_id], r.duration_ms, rawRel, wavRel, s.gender, s.age_band, s.region, s.mother_tongue, s.device, s.environment].map(q).join(','));
}
writeFileSync(join(out, 'metadata.csv'), '﻿' + lines.join('\n'), 'utf8');
writeFileSync(
  join(out, 'sentences.tsv'),
  '﻿' + ['id\tgroup\ttext\tref', ...SENTENCES.map((s) => [s.id, s.group, s.text, s.ref ?? ''].join('\t'))].join('\n'),
  'utf8',
);
console.log(`Exported ${recs.length} clips from ${speakers.length} speakers to ${out}`);
await pool.end();
