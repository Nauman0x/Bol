import { db } from '../../../../lib/db';

export const runtime = 'nodejs';

export async function GET(req) {
  const id = parseInt(new URL(req.url).searchParams.get('id') || '', 10);
  if (!Number.isInteger(id)) return new Response('Bad request', { status: 400 });
  const pool = await db();
  const r = await pool.query('SELECT audio FROM evalrec.stimuli WHERE id = $1', [id]);
  if (!r.rowCount) return new Response('Not found', { status: 404 });
  return new Response(r.rows[0].audio, {
    headers: { 'content-type': 'audio/wav', 'cache-control': 'private, max-age=3600' },
  });
}
