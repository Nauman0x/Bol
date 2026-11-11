import { db } from '../../../lib/db';

export const runtime = 'nodejs';

export async function GET(req) {
  const speaker = new URL(req.url).searchParams.get('speaker') || '';
  const pool = await db();
  const ok = await pool.query('SELECT 1 FROM evalrec.speakers WHERE id = $1', [speaker]);
  if (!ok.rowCount) return Response.json({ error: 'Unknown speaker' }, { status: 404 });
  const r = await pool.query('SELECT sentence_id FROM evalrec.recordings WHERE speaker_id = $1', [speaker]);
  return Response.json({ done: r.rows.map((x) => x.sentence_id) });
}
