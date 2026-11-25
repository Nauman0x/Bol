"""gen_eval.py : generate replies for the held-out eval set (and probe_30) with the SAME nf4 base, adapter off vs on,
so base-vs-fine-tuned differs only by the LoRA. Greedy, max 100 new tokens. Run inside .venv-train.
  python scripts/gen_eval.py [--adapter models/lora-c1] [--tag c1]
Writes data/work/eval/<set>_{base,<tag>}.jsonl rows: {id, tag, model, reply}."""
import argparse, json, pathlib, re

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--base", default=str(ROOT / "models/qwen25-bnb4"))
ap.add_argument("--adapter", default=str(ROOT / "models/lora-c1"))
ap.add_argument("--tag", default="c1")
a = ap.parse_args()

systems = json.loads((ROOT / "data/bakeoff/probe_systems.json").read_text(encoding="utf-8"))
sets = {"eval40": ROOT / "data/sft/eval_40.jsonl", "probe30": ROOT / "data/bakeoff/probe_30.jsonl"}
tok = AutoTokenizer.from_pretrained(a.base)
model = AutoModelForCausalLM.from_pretrained(a.base, device_map={"": 0}, torch_dtype=torch.bfloat16)
model = PeftModel.from_pretrained(model, a.adapter)
model.eval()
out_dir = ROOT / "data/work/eval"; out_dir.mkdir(parents=True, exist_ok=True)


def reply(t):
    system = systems["common_rules"] + "\n\n" + systems[t["biz"]]
    msgs = [{"role": "system", "content": system}, *t["history"], {"role": "user", "content": t["user"]}]
    ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True).to("cuda")
    with torch.no_grad():
        o = model.generate(**ids, max_new_tokens=100, do_sample=False, pad_token_id=tok.pad_token_id)
    return tok.decode(o[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


for name, path in sets.items():
    turns = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    for label, off in (("base", True), (a.tag, False)):
        rows = []
        for t in turns:
            if off:
                with model.disable_adapter():
                    txt = reply(t)
            else:
                txt = reply(t)
            rows.append({"id": t["id"], "tag": t["tag"], "model": f"{name}_{label}", "reply": txt})
        p = out_dir / f"{name}_{label}.jsonl"
        p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        print(p.name, len(rows), "avg words", sum(len(r["reply"].split()) for r in rows) / len(rows), flush=True)
