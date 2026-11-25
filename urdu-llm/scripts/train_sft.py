"""train_sft.py : QLoRA fine-tune of Qwen2.5-7B-Instruct (pre-quantised bnb-4bit base) on data/sft/train.jsonl.
Loss only on the assistant reply. Run inside .venv-train:  python scripts/train_sft.py [--epochs 3]
Writes the LoRA adapter to models/lora-c1 and a loss log to report/train/."""
import argparse, json, pathlib, random

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--base", default=str(ROOT / "models/qwen25-bnb4"))
ap.add_argument("--train", default=str(ROOT / "data/sft/train.jsonl"))
ap.add_argument("--out", default=str(ROOT / "models/lora-c1"))
ap.add_argument("--epochs", type=int, default=3)
ap.add_argument("--lr", type=float, default=2e-4)
ap.add_argument("--bs", type=int, default=4)
ap.add_argument("--rank", type=int, default=16)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
random.seed(a.seed); torch.manual_seed(a.seed)

systems = json.loads((ROOT / "data/bakeoff/probe_systems.json").read_text(encoding="utf-8"))
tok = AutoTokenizer.from_pretrained(a.base)
rows = [json.loads(l) for l in pathlib.Path(a.train).read_text(encoding="utf-8").splitlines() if l.strip()]


def encode(r):
    system = systems["common_rules"] + "\n\n" + systems[r["biz"]]
    msgs = [{"role": "system", "content": system}, *r["history"], {"role": "user", "content": r["user"]}]
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    a_ids = tok(r["assistant"] + "<|im_end|>\n", add_special_tokens=False)["input_ids"]
    return p_ids + a_ids, [-100] * len(p_ids) + a_ids[:-1] + [-100]  # do not train on the trailing newline


data = [encode(r) for r in rows]
print(f"{len(data)} examples, max len {max(len(x[0]) for x in data)}")

model = AutoModelForCausalLM.from_pretrained(a.base, device_map={"": 0}, torch_dtype=torch.bfloat16)
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
                                         target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
model.print_trainable_parameters()

opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
steps = a.epochs * ((len(data) + a.bs - 1) // a.bs)
sched = get_cosine_schedule_with_warmup(opt, max(1, steps // 10), steps)
log, step = [], 0
model.train()
for ep in range(a.epochs):
    random.shuffle(data)
    for i in range(0, len(data), a.bs):
        batch = data[i:i + a.bs]
        L = max(len(x[0]) for x in batch)
        ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in batch]).cuda()
        lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in batch]).cuda()
        att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in batch]).cuda()
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
        step += 1
        log.append({"step": step, "epoch": ep, "loss": loss.item()})
        if step % 5 == 0 or step == steps:
            print(f"step {step}/{steps} epoch {ep} loss {loss.item():.4f} vram {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB", flush=True)

model.save_pretrained(a.out)
rep = ROOT / "report/train"; rep.mkdir(parents=True, exist_ok=True)
(rep / "loss_c1.json").write_text(json.dumps({"args": vars(a), "log": log}, indent=1), encoding="utf-8")
print("saved", a.out)
