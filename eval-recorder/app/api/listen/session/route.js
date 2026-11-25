import { randomUUID } from 'node:crypto';
import { db } from '../../../../lib/db';

export const runtime = 'nodejs';

const clip = (v, n = 80) => (typeof v === 'string' ? v.slice(0, n) : null);

export async function POST(req) {
  const b = await req.json().catch(() => ({}));
  if (!b.consent) return Response.json({ error: 'Consent is required' }, { status: 400 });
  const pool = await db();
  const n = await pool.query('SELECT count(*)::int AS n FROM evalrec.stimuli');
  if (!n.rows[0].n) return Response.json({ error: 'The listening test is not open yet.' }, { status: 503 });
  const id = randomUUID().slice(0, 8);
  await pool.query(
    `INSERT INTO evalrec.raters (id, consent_at, native, age_band, region, gender, listening_device, user_agent)
     VALUES ($1, now(), $2, $3, $4, $5, $6, $7)`,
    [id, clip(b.native), clip(b.age_band), clip(b.region), clip(b.gender), clip(b.listening_device), clip(req.headers.get('user-agent'), 200)],
  );
  return Response.json({ raterId: id });
}
