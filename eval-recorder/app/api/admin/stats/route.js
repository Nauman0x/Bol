import { db } from '../../../../lib/db';

export const runtime = 'nodejs';

export async function GET(req) {
  const token = req.headers.get('x-admin-token');
  if (!process.env.ADMIN_TOKEN || token !== process.env.ADMIN_TOKEN) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const pool = await db();
  const r = await pool.query(`
    SELECT s.id, s.created_at, s.gender, s.age_band, s.region, s.device, s.environment,
           COUNT(r.id)::int AS clips, COALESCE(SUM(octet_length(r.audio)),0)::bigint AS bytes
    FROM evalrec.speakers s LEFT JOIN evalrec.recordings r ON r.speaker_id = s.id
    GROUP BY s.id ORDER BY s.created_at DESC`);
  return Response.json({ speakers: r.rows });
}
