import { db } from '../../../../lib/db';
import { buildPlan } from '../../../../lib/plan';

export const runtime = 'nodejs';

export async function GET(req) {
  const rater = new URL(req.url).searchParams.get('rater') || '';
  const pool = await db();
  const ok = await pool.query('SELECT 1 FROM evalrec.raters WHERE id = $1', [rater]);
  if (!ok.rowCount) return Response.json({ error: 'Unknown rater' }, { status: 404 });
  const st = await pool.query('SELECT id, sentence_id, system, grp FROM evalrec.stimuli');
  const done = await pool.query('SELECT trial_idx FROM evalrec.ratings WHERE rater_id = $1', [rater]);
  return Response.json({ trials: buildPlan(rater, st.rows), done: done.rows.map((r) => r.trial_idx) });
}
