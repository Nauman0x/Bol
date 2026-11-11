import { db } from '../../../lib/db';
import { SENTENCE_IDS } from '../../../lib/sentences';

export const runtime = 'nodejs';

const MAX_BYTES = 3_000_000; // well under Vercel's ~4.5 MB request limit

export async function POST(req) {
  const u = new URL(req.url);
  const speaker = u.searchParams.get('speaker') || '';
  const sentence = u.searchParams.get('sentence') || '';
  const duration = parseInt(u.searchParams.get('duration') || '0', 10) || null;
  const mime = (req.headers.get('content-type') || 'application/octet-stream').slice(0, 60);
  if (!SENTENCE_IDS.has(sentence)) return Response.json({ error: 'Bad sentence' }, { status: 400 });
  const buf = Buffer.from(await req.arrayBuffer());
  if (buf.length < 1000) return Response.json({ error: 'Recording too short' }, { status: 400 });
  if (buf.length > MAX_BYTES) return Response.json({ error: 'Recording too large' }, { status: 413 });
  const pool = await db();
  const ok = await pool.query('SELECT 1 FROM evalrec.speakers WHERE id = $1', [speaker]);
  if (!ok.rowCount) return Response.json({ error: 'Unknown speaker' }, { status: 404 });
  await pool.query(
    `INSERT INTO evalrec.recordings (speaker_id, sentence_id, mime, duration_ms, audio)
     VALUES ($1,$2,$3,$4,$5)
     ON CONFLICT (speaker_id, sentence_id)
     DO UPDATE SET mime = EXCLUDED.mime, duration_ms = EXCLUDED.duration_ms, audio = EXCLUDED.audio, created_at = now()`,
    [speaker, sentence, mime, duration, buf],
  );
  return Response.json({ ok: true });
}
