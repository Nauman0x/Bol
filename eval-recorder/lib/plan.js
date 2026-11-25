// Deterministic listening-test plan per rater (seeded by the rater id), so a rater who comes back sees the
// same trials in the same order, and the server can check every answer against the plan.
// Clips are referred to by opaque numeric stimulus ids; system names never leave the server.

function rng(seedStr) {
  let h = 2166136261;
  for (const c of seedStr) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = (h + 0x6d2b79f5) | 0;
    let t = Math.imul(h ^ (h >>> 15), 1 | h);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(arr, rand) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// v2: Esha's held-out sentences. esha_real is the human ceiling (same speaker as esha_voice).
const SYSTEMS = ['esha_real', 'esha_voice', 'bol_rasa_female', 'stock_fasih'];
const PER_GROUP = { esha: 10 }; // 10 sentences per rater

/** stimuli: [{id, sentence_id, system, grp}] -> trials: [{idx, kind, a, b?}] */
export function buildPlan(raterId, stimuli) {
  const rand = rng(raterId);
  const byKey = new Map(stimuli.map((s) => [`${s.sentence_id}|${s.system}`, s.id]));
  const sentences = [...new Set(stimuli.map((s) => s.sentence_id))];
  const grpOf = new Map(stimuli.map((s) => [s.sentence_id, s.grp]));
  const complete = sentences.filter((sid) => [...SYSTEMS, 'anchor'].every((sys) => byKey.has(`${sid}|${sys}`)));

  // Part 1: absolute rating (MOS). 10 sentences x 4 systems, plus the low anchor on 2 of them.
  const chosen = [];
  for (const [g, n] of Object.entries(PER_GROUP)) {
    chosen.push(...shuffle(complete.filter((sid) => grpOf.get(sid) === g), rand).slice(0, n));
  }
  const mos = [];
  for (const sid of chosen) for (const sys of SYSTEMS) mos.push({ kind: 'mos', a: byKey.get(`${sid}|${sys}`) });
  for (const sid of shuffle(chosen, rand).slice(0, 2)) mos.push({ kind: 'mos', a: byKey.get(`${sid}|anchor`) });

  // Part 2: A/B preference on sentences not used above (falls back to any sentence).
  const spare = shuffle(complete.filter((sid) => !chosen.includes(sid)), rand);
  const pick = (i) => spare[i % Math.max(1, spare.length)] ?? chosen[i % chosen.length];
  const pairs = [['esha_voice', 'stock_fasih'], ['esha_voice', 'bol_rasa_female'], ['esha_voice', 'esha_real']];
  const ab = pairs.map(([x, y], i) => {
    const sid = pick(i);
    const flip = rand() < 0.5;
    const [p, q] = flip ? [y, x] : [x, y];
    return { kind: 'ab', a: byKey.get(`${sid}|${p}`), b: byKey.get(`${sid}|${q}`) };
  });

  // Part 3: accent rating, one clip per system.
  const accent = shuffle(SYSTEMS, rand).map((sys, i) => ({ kind: 'accent', a: byKey.get(`${pick(i + 3)}|${sys}`) }));

  return [...shuffle(mos, rand), ...ab, ...accent].map((t, idx) => ({ idx, ...t }));
}
