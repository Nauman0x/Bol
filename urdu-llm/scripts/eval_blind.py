"""eval_blind.py : blind in-session judging for the base-vs-fine-tuned comparison.
  python scripts/eval_blind.py export   -> data/work/eval_judge/eval.in.jsonl (blind) + eval.key.json (do not open while scoring)
  python scripts/eval_blind.py score    -> report/finetune/eval_scores.json (reads eval.out.jsonl: item, understood, register, tone, faithful)
Sets judged: eval40 base, eval40 tuned (held-out turns) and probe30 tuned (bake-off turns, comparable to the earlier Qwen2.5 row)."""
import importlib.util, json, pathlib, random, statistics as st, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EV = ROOT / "data/work/eval"
JD = ROOT / "data/work/eval_judge"
spec = importlib.util.spec_from_file_location("bm", ROOT / "scripts/bench_models.py")
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
SETS = ["eval40_base", "eval40_c1", "probe30_c1"]
CRIT = ["understood", "register", "tone", "faithful"]


def turns():
    t = {}
    for name, p in (("eval40", ROOT / "data/sft/eval_40.jsonl"), ("probe30", ROOT / "data/bakeoff/probe_30.jsonl")):
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l); t[(name, r["id"])] = r
    return t


def load(name):
    return [json.loads(l) for l in (EV / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def export():
    T = turns(); rows = []
    for s in SETS:
        for r in load(s):
            rows.append({**r, "set": s})
    random.Random(21).shuffle(rows)
    JD.mkdir(parents=True, exist_ok=True)
    key, blind = {}, []
    for i, r in enumerate(rows):
        item = f"q{i:03d}"
        t = T[(r["set"].split("_")[0], r["id"])]
        key[item] = {"id": r["id"], "set": r["set"], "tag": r["tag"]}
        blind.append({"item": item, "business": t["biz"], "history": t["history"], "caller": t["user"], "reply": r["reply"]})
    (JD / "eval.in.jsonl").write_text("\n".join(json.dumps(b, ensure_ascii=False) for b in blind), encoding="utf-8")
    (JD / "eval.key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(len(blind), "blind items ->", JD / "eval.in.jsonl")


def score():
    key = json.loads((JD / "eval.key.json").read_text())
    sc = {j["item"]: j for j in map(json.loads, (JD / "eval.out.jsonl").read_text(encoding="utf-8").splitlines()) if j}
    rep = {s: {r["id"]: r for r in load(s)} for s in SETS}
    out = {}
    for item, k in key.items():
        if item not in sc:
            continue
        m = out.setdefault(k["set"], {"overall": [], "rules": {}, "bytag": {}, **{c: [] for c in CRIT}})
        v = [sc[item][c] for c in CRIT]
        for c, x in zip(CRIT, v):
            m[c].append(x)
        m["overall"].append(st.mean(v))
        m["bytag"].setdefault(k["tag"], []).append(st.mean(v))
        for rc, ok in bm.rule_checks(rep[k["set"]][k["id"]]["reply"], k["tag"]).items():
            m["rules"].setdefault(rc, []).append(ok)
    table = {}
    for s, m in out.items():
        lo, hi = bm.bootstrap_ci(m["overall"])
        table[s] = {"n": len(m["overall"]), "overall": {"mean": st.mean(m["overall"]), "ci95": [lo, hi]},
                    **{c: st.mean(m[c]) for c in CRIT}, "rules_pass": {r: sum(v) / len(v) for r, v in m["rules"].items()},
                    "by_tag": {t: round(st.mean(v), 2) for t, v in sorted(m["bytag"].items())}}
        print(f"{s:12s} n={table[s]['n']} overall {st.mean(m['overall']):.2f} [{lo:.2f},{hi:.2f}] "
              + " ".join(f"{c}={st.mean(m[c]):.2f}" for c in CRIT) + " | rules " + json.dumps({r: round(x, 2) for r, x in table[s]["rules_pass"].items()}))
        print("   by tag:", table[s]["by_tag"])
    d = ROOT / "report/finetune"; d.mkdir(parents=True, exist_ok=True)
    (d / "eval_scores.json").write_text(json.dumps(table, indent=2), encoding="utf-8")


{"export": export, "score": score}[sys.argv[1]]()
