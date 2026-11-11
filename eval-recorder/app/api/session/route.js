import { randomUUID } from 'node:crypto';
import { db } from '../../../lib/db';

export const runtime = 'nodejs';

const clip = (v, n = 80) => (typeof v === 'string' ? v.slice(0, n) : null);

export async function POST(req) {
  const b = await req.json().catch(() => ({}));
  if (!b.consent) return Response.json({ error: 'Consent is required' }, { status: 400 });
  const id = randomUUID().slice(0, 8);
  const pool = await db();
  await pool.query(
    `INSERT INTO evalrec.speakers (id, consent_at, gender, age_band, region, mother_tongue, device, environment, user_agent)
     VALUES ($1, now(), $2, $3, $4, $5, $6, $7, $8)`,
    [id, clip(b.gender), clip(b.age_band), clip(b.region), clip(b.mother_tongue), clip(b.device), clip(b.environment), clip(req.headers.get('user-agent'), 200)],
  );
  return Response.json({ speakerId: id });
}
