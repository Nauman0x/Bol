import { db } from '../../../../lib/db';
import { buildPlan } from '../../../../lib/plan';

export const runtime = 'nodejs';

export async function POST(req) {
  const b = await req.json().catch(() => ({}));
  const pool = await db();
  const ok = await pool.query('SELECT 1 FROM evalrec.raters WHERE id = $1', [b.rater]);
  if (!ok.rowCount) return Response.json({ error: 'Unknown rater' }, { status: 404 });
  const st = await pool.query('SELECT id, sentence_id, system, grp FROM evalrec.stimuli');
  const trial = buildPlan(b.rater, st.rows)[b.idx];
  if (!trial) return Response.json({ error: 'Bad trial' }, { status: 400 });

  let score = null;
  let choice = null;
  if (trial.kind === 'ab') {
    if (!['A', 'B', 'same'].includes(b.choice)) return Response.json({ error: 'Bad choice' }, { status: 400 });
    choice = b.choice;
  } else {
    score = parseInt(b.score, 10);
    if (!(score >= 1 && score <= 5)) return Response.json({ error: 'Bad score' }, { status: 400 });
  }
  await pool.query(
    `INSERT INTO evalrec.ratings (rater_id, trial_idx, kind, stim_a, stim_b, score, choice, listen_ms)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
     ON CONFLICT (rater_id, trial_idx) DO UPDATE SET score = EXCLUDED.score, choice = EXCLUDED.choice, created_at = now()`,
    [b.rater, b.idx, trial.kind, trial.a, trial.b ?? null, score, choice, parseInt(b.listen_ms, 10) || null],
  );
  return Response.json({ ok: true });
}
