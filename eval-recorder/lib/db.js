import pg from 'pg';

let pool;
let ready;

function getPool() {
  if (!pool) {
    const url = process.env.AIVEN_DATABASE_URL;
    if (!url) throw new Error('AIVEN_DATABASE_URL is not set');
    // pg reads sslmode from the URL and would override our ssl option; strip it and set ssl explicitly.
    const clean = url.replace(/[?&]sslmode=[^&]*/g, '').replace(/\?$/, '');
    const ca = process.env.AIVEN_CA_CERT;
    pool = new pg.Pool({
      connectionString: clean,
      ssl: ca ? { ca, rejectUnauthorized: true } : { rejectUnauthorized: false },
      max: 3,
    });
  }
  return pool;
}

export async function db() {
  const p = getPool();
  ready ??= p
    .query(`
      CREATE SCHEMA IF NOT EXISTS evalrec;
      CREATE TABLE IF NOT EXISTS evalrec.speakers (
        id            TEXT PRIMARY KEY,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        consent_at    TIMESTAMPTZ NOT NULL,
        gender        TEXT, age_band TEXT, region TEXT, mother_tongue TEXT,
        device        TEXT, environment TEXT, user_agent TEXT
      );
      CREATE TABLE IF NOT EXISTS evalrec.recordings (
        id          BIGSERIAL PRIMARY KEY,
        speaker_id  TEXT NOT NULL REFERENCES evalrec.speakers(id) ON DELETE CASCADE,
        sentence_id TEXT NOT NULL,
        mime        TEXT NOT NULL,
        duration_ms INTEGER,
        audio       BYTEA NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (speaker_id, sentence_id)
      );
    `)
    .catch((e) => {
      ready = undefined;
      throw e;
    });
  await ready;
  return p;
}
