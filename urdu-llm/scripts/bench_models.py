#!/usr/bin/env python3
"""Phase 1 bake-off: tokenizer fertility, raw serving latency, blind Urdish quality probe.

  fertility     tokens/word and tokens/char on the Roman-Urdu and Urdu-script sentence sets
  latency       streaming TTFT / TTFS / decode speed at 1, 2, 4 concurrent streams
  probe-gen     run the 30 probe turns through a served model (greedy, prompt-only)
  probe-export  build the blind, shuffled judge file from all probe-gen outputs
  probe-score   unblind judge scores, add rule checks, bootstrap CIs

Works against any OpenAI-compatible server (vLLM, llama-server, Groq).
No credentials are stored: Groq needs GROQ_API_KEY in the environment.
"""
import argparse
import asyncio
import json
import os
import random
import re
import statistics as st
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "bakeoff"
WORK = ROOT / "data" / "work"
REPORT = ROOT / "report" / "bakeoff"

MODELS = {
    "qwen25-7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen3-8b": "Qwen/Qwen3-8B",
    "qalb-8b": "enstazao/Qalb-1.0-8B-Instruct",
}
CLAUSE_END = ",.?!،۔؟"
ARABIC_RE = re.compile(r"[؀-ۿ]")
MARKDOWN_RE = re.compile(r"[*_#`>\[\]{}|]|^\s*[-•\d]+[.)]\s", re.M)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def load_lines(p):
    return [l.strip() for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]


def load_probe():
    systems = json.loads((DATA / "probe_systems.json").read_text(encoding="utf-8"))
    turns = [json.loads(l) for l in (DATA / "probe_30.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return systems, turns


def build_messages(systems, turn, nonce=None):
    system = systems["common_rules"] + "\n\n" + systems[turn["biz"]]
    if nonce:
        system = f"[session {nonce}] " + system
    return [{"role": "system", "content": system}, *turn["history"], {"role": "user", "content": turn["user"]}]


# ----------------------------------------------------------------------------- fertility
def cmd_fertility(a):
    from transformers import AutoTokenizer

    sets = {"roman": load_lines(DATA / "roman_urdu_100.txt"), "urdu": load_lines(DATA / "urdu_script_100.txt")}
    out = {}
    for tag, repo in MODELS.items():
        tok = AutoTokenizer.from_pretrained(repo)
        out[tag] = {"repo": repo, "vocab": len(tok)}
        for sname, sents in sets.items():
            counts = [len(tok.encode(s, add_special_tokens=False)) for s in sents]
            words = sum(len(s.split()) for s in sents)
            chars = sum(len(s) for s in sents)
            out[tag][sname] = {
                "n": len(sents),
                "tokens_per_word": sum(counts) / words,
                "tokens_per_char": sum(counts) / chars,
                "mean_tokens_per_sentence": st.mean(counts),
                "p95_tokens_per_sentence": pct(counts, 0.95),
            }
        print(f"{tag:10s} roman {out[tag]['roman']['tokens_per_word']:.2f} tok/word | urdu {out[tag]['urdu']['tokens_per_word']:.2f} tok/word")
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "fertility.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------- latency
class VramSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak = 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                v = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True
                )
                self.peak = max(self.peak, int(v.strip().splitlines()[0]))
            except Exception:
                return
            time.sleep(0.5)


def request_body(a, messages):
    body = {"model": a.model, "messages": messages, "stream": True, "temperature": 0.0,
            "max_tokens": a.max_tokens, "stream_options": {"include_usage": True}}
    if a.no_think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if a.reasoning_effort:
        body["reasoning_effort"] = a.reasoning_effort
    if a.ignore_eos:
        body["ignore_eos"] = True
    if a.stop:
        body["stop"] = a.stop
    return body


class RateLimited(Exception):
    pass


async def one_stream(client, a, headers, messages):
    """Retry on HTTP 429 (hosted free tiers); the wait is outside the timed attempt."""
    for _ in range(8):
        try:
            return await _one_stream(client, a, headers, messages)
        except RateLimited as e:
            await asyncio.sleep(float(e.args[0]))
    raise RuntimeError("still rate limited after 8 retries")


async def _one_stream(client, a, headers, messages):
    t0 = time.perf_counter()
    ttft = ttfs = None
    text, usage = "", None
    async with client.stream("POST", a.base_url + "/chat/completions", json=request_body(a, messages), headers=headers) as r:
        if r.status_code == 429:
            m = re.search(r"try again in ([\d.]+)s", (await r.aread()).decode(errors="ignore"))
            raise RateLimited(float(m.group(1)) + 0.5 if m else 5.0)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {(await r.aread())[:300]!r}")
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            obj = json.loads(data)
            usage = obj.get("usage") or (obj.get("x_groq") or {}).get("usage") or usage
            for ch in obj.get("choices", []):
                d = (ch.get("delta") or {}).get("content") or ""
                if not d:
                    continue
                now = time.perf_counter() - t0
                ttft = ttft if ttft is not None else now
                text += d
                if ttfs is None and (any(c in CLAUSE_END for c in text) or len(text) >= a.clause_chars):
                    ttfs = now
    total = time.perf_counter() - t0
    ctoks = (usage or {}).get("completion_tokens")
    return {
        "ttft_ms": None if ttft is None else ttft * 1000,
        "ttfs_ms": None if ttfs is None else ttfs * 1000,
        "total_ms": total * 1000,
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "completion_tokens": ctoks,
        "decode_tok_s": (ctoks - 1) / (total - ttft) if ctoks and ctoks > 1 and ttft and total > ttft else None,
        "words": len(text.split()),
        "text": text,
    }


async def run_level(a, concurrency, systems, turns, headers):
    import httpx

    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency * 2)
    async with httpx.AsyncClient(timeout=120, limits=limits) as client:
        def msgs(i):
            nonce = f"{random.getrandbits(48):012x}" if a.cold else None
            return build_messages(systems, turns[i % len(turns)], nonce)

        for i in range(a.warmup):  # warm connection, CUDA graphs, prefix cache
            await one_stream(client, a, headers, msgs(i))
        results, counter = [], iter(range(a.requests))

        async def worker():
            for i in counter:
                results.append(await one_stream(client, a, headers, msgs(i)))

        t0 = time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(concurrency)])
        wall = time.perf_counter() - t0
    return results, wall


def summarise(rs):
    col = lambda k: [r[k] for r in rs if r.get(k) is not None]
    return {
        "n": len(rs),
        "ttft_p50": pct(col("ttft_ms"), 0.5), "ttft_p95": pct(col("ttft_ms"), 0.95),
        "ttfs_p50": pct(col("ttfs_ms"), 0.5), "ttfs_p95": pct(col("ttfs_ms"), 0.95),
        "decode_tok_s_p50": pct(col("decode_tok_s"), 0.5),
        "prompt_tokens_mean": st.mean(col("prompt_tokens")) if col("prompt_tokens") else None,
        "completion_tokens_mean": st.mean(col("completion_tokens")) if col("completion_tokens") else None,
        "words_mean": st.mean(col("words")),
    }


def cmd_latency(a):
    systems, turns = load_probe()
    headers = {"Authorization": f"Bearer {os.environ.get(a.key_env, 'EMPTY')}"}
    if a.key_env != "NONE" and a.key_env != "EMPTY" and a.base_url.startswith("https") and a.key_env not in os.environ:
        raise SystemExit(f"set {a.key_env} in the environment first")
    sampler = VramSampler()
    base_vram = None
    if not a.base_url.startswith("https"):
        sampler.start()
        time.sleep(1.0)
        base_vram = sampler.peak
    REPORT.mkdir(parents=True, exist_ok=True)
    with open(REPORT / "latency.jsonl", "a", encoding="utf-8") as f:
        for c in a.concurrency:
            rs, wall = asyncio.run(run_level(a, c, systems, turns, headers))
            row = {"tag": a.tag, "model": a.model, "cold_prefix": a.cold, "concurrency": c,
                   "throughput_req_s": len(rs) / wall, "vram_peak_mib": sampler.peak or None,
                   "vram_idle_mib": base_vram, **summarise(rs)}
            f.write(json.dumps(row) + "\n")
            print(json.dumps({k: (round(v, 1) if isinstance(v, float) else v) for k, v in row.items()}))
            if a.dump:
                (REPORT / f"raw_{a.tag}_c{c}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rs), encoding="utf-8")
    sampler.stop.set()


# ----------------------------------------------------------------------------- quality probe
def cmd_probe_gen(a):
    import httpx

    systems, turns = load_probe()
    headers = {"Authorization": f"Bearer {os.environ.get(a.key_env, 'EMPTY')}"}
    out = WORK / "probe"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=120) as client:
        for t in turns:
            body = request_body(a, build_messages(systems, t))
            body["stream"] = False
            body.pop("stream_options")
            for _ in range(8):
                r = client.post(a.base_url + "/chat/completions", json=body, headers=headers)
                if r.status_code != 429:
                    break
                m = re.search(r"try again in ([\d.]+)s", r.text)
                time.sleep(float(m.group(1)) + 0.5 if m else 5.0)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"] or ""
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            rows.append({"id": t["id"], "tag": t["tag"], "model": a.tag, "reply": text})
    (out / f"{a.tag}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    print(f"{a.tag}: {len(rows)} replies -> {out / (a.tag + '.jsonl')}")


def cmd_probe_export(a):
    _, turns = load_probe()
    by_id = {t["id"]: t for t in turns}
    rows = []
    for p in sorted((WORK / "probe").glob("*.jsonl")):
        rows += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    rng = random.Random(a.seed)
    rng.shuffle(rows)
    judge = WORK / "judge"
    judge.mkdir(parents=True, exist_ok=True)
    key, blind = {}, []
    for i, r in enumerate(rows):
        item = f"p{i:03d}"
        key[item] = {"id": r["id"], "model": r["model"]}
        t = by_id[r["id"]]
        blind.append({"item": item, "business": t["biz"], "history": t["history"], "caller": t["user"], "reply": r["reply"]})
    (judge / "probe.in.jsonl").write_text("\n".join(json.dumps(b, ensure_ascii=False) for b in blind), encoding="utf-8")
    (judge / "probe.key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(blind)} blind items -> {judge / 'probe.in.jsonl'} (key kept in probe.key.json, do not open while scoring)")


def rule_checks(reply, tag):
    words = len(reply.split())
    return {
        "short": words <= 35,
        "no_markup": not MARKDOWN_RE.search(reply) and not EMOJI_RE.search(reply),
        "roman_only": not ARABIC_RE.search(reply),
        "digits_spoken": not (tag == "phone" and re.search(r"\d{3,}", reply)),
    }


def bootstrap_ci(xs, n=2000, seed=0):
    rng = random.Random(seed)
    means = sorted(st.mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def cmd_probe_score(a):
    judge = WORK / "judge"
    key = json.loads((judge / "probe.key.json").read_text())
    scores = {j["item"]: j for j in map(json.loads, (judge / "probe.out.jsonl").read_text(encoding="utf-8").splitlines()) if j}
    replies = {}
    for p in (WORK / "probe").glob("*.jsonl"):
        for l in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            replies[(r["model"], r["id"])] = r
    crit = ["understood", "register", "tone", "faithful"]
    per_model = {}
    for item, k in key.items():
        if item not in scores:
            continue
        s, r = scores[item], replies[(k["model"], k["id"])]
        m = per_model.setdefault(k["model"], {c: [] for c in crit} | {"rules": {}})
        for c in crit:
            m[c].append(s[c])
        for rc, ok in rule_checks(r["reply"], r["tag"]).items():
            m["rules"].setdefault(rc, []).append(ok)
    table = {}
    for model, m in per_model.items():
        row = {}
        for c in crit:
            lo, hi = bootstrap_ci(m[c])
            row[c] = {"mean": st.mean(m[c]), "ci95": [lo, hi]}
        allv = [st.mean(v) for v in zip(*(m[c] for c in crit))]
        lo, hi = bootstrap_ci(allv)
        row["overall"] = {"mean": st.mean(allv), "ci95": [lo, hi]}
        row["rules_pass"] = {rc: sum(v) / len(v) for rc, v in m["rules"].items()}
        row["n"] = len(allv)
        table[model] = row
        print(f"{model:12s} overall {row['overall']['mean']:.2f} [{lo:.2f},{hi:.2f}] n={len(allv)} | "
              + " ".join(f"{c}={row[c]['mean']:.2f}" for c in crit) + " | rules " + json.dumps(row["rules_pass"]))
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "probe_scores.json").write_text(json.dumps(table, indent=2), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fertility").set_defaults(fn=cmd_fertility)

    def server_args(sp):
        sp.add_argument("--base-url", default="http://localhost:8000/v1")
        sp.add_argument("--model", required=True, help="model name as the server knows it")
        sp.add_argument("--tag", required=True, help="short label for this model+serving form")
        sp.add_argument("--key-env", default="EMPTY", help="env var holding the API key (e.g. GROQ_API_KEY)")
        sp.add_argument("--no-think", action="store_true", help="disable Qwen3 thinking via chat_template_kwargs")
        sp.add_argument("--reasoning-effort", default=None)
        sp.add_argument("--stop", nargs="+", default=None, help="stop strings (Qalb GGUF has no <|im_end|> EOS)")
        sp.add_argument("--max-tokens", type=int, default=100)

    sp = sub.add_parser("latency")
    server_args(sp)
    sp.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    sp.add_argument("--requests", type=int, default=40)
    sp.add_argument("--warmup", type=int, default=4)
    sp.add_argument("--cold", action="store_true", help="unique prefix per request (defeats prefix caching)")
    sp.add_argument("--ignore-eos", action="store_true")
    sp.add_argument("--clause-chars", type=int, default=24, help="TTFS fallback: chars before a clause end")
    sp.add_argument("--dump", action="store_true")
    sp.set_defaults(fn=cmd_latency)

    sp = sub.add_parser("probe-gen")
    server_args(sp)
    sp.set_defaults(fn=cmd_probe_gen, ignore_eos=False)
    sp = sub.add_parser("probe-export")
    sp.add_argument("--seed", type=int, default=7)
    sp.set_defaults(fn=cmd_probe_export)
    sub.add_parser("probe-score").set_defaults(fn=cmd_probe_score)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
