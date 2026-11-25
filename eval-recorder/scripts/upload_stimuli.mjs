// Upload the listening-test clips (urdu-eval/data/listening) into the database, in shuffled order so
// the numeric ids do not reveal which system a clip belongs to. Safe to re-run: existing clips are kept.
//   node scripts/upload_stimuli.mjs
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import pg from 'pg';

function loadEnv(path) {
  try {
    for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^([A-Z_]+)=(.*)$/);
      if (m && !(m[1] in process.env)) process.env[m[1]] = m[2];
    }
  } catch {}
}
loadEnv(new URL('../.env.local', import.meta.url));

const dir = fileURLToPath(new URL('../../urdu-eval/data/listening/', import.meta.url));
const tsv = readFileSync(join(dir, 'stimuli.tsv'), 'utf8').replace(/^﻿/, '').trim().split(/\r?\n/);
const head = tsv[0].split('\t');
const rows = tsv.slice(1).map((l) => Object.fromEntries(l.split('\t').map((v, i) => [head[i], v])));
for (let i = rows.length - 1; i > 0; i--) {
  const j = Math.floor(Math.random() * (i + 1));
  [rows[i], rows[j]] = [rows[j], rows[i]];
}

const ca = process.env.AIVEN_CA_CERT;
const pool = new pg.Pool({
  connectionString: process.env.AIVEN_DATABASE_URL.replace(/[?&]sslmode=[^&]*/g, '').replace(/\?$/, ''),
  ssl: ca ? { ca } : { rejectUnauthorized: false },
  max: 2,
});

// make sure the tables exist (same DDL as the app)
await pool.query(`
  CREATE SCHEMA IF NOT EXISTS evalrec;
  CREATE TABLE IF NOT EXISTS evalrec.stimuli (
    id SERIAL PRIMARY KEY, sentence_id TEXT NOT NULL, system TEXT NOT NULL, grp TEXT NOT NULL,
    audio BYTEA NOT NULL, UNIQUE (sentence_id, system));
`);
// OVERWRITE=1 replaces the audio of clips that already exist (ids are kept, so they stay blind)
const OVERWRITE = process.env.OVERWRITE === '1';
let added = 0;
for (const r of rows) {
  const res = await pool.query(
    `INSERT INTO evalrec.stimuli (sentence_id, system, grp, audio) VALUES ($1,$2,$3,$4) ON CONFLICT (sentence_id, system) ${OVERWRITE ? 'DO UPDATE SET audio = EXCLUDED.audio' : 'DO NOTHING'}`,
    [r.sentence_id, r.system, r.group, readFileSync(join(dir, r.file))],
  );
  added += res.rowCount;
}
const n = await pool.query('SELECT count(*)::int AS n, pg_size_pretty(sum(octet_length(audio))) AS size FROM evalrec.stimuli');
console.log(`${OVERWRITE ? 'wrote' : 'added'} ${added} clips; table now holds ${n.rows[0].n} clips (${n.rows[0].size})`);
await pool.end();
