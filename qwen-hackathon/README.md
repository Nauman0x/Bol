# Qwen Local Hackathon 2026 – Project Requirements

Organizer: Qwen Pakistan. Fully online, free. Registered: yes (confirmed).

## Timeline (Pakistan time)

| Date | Event |
|---|---|
| Fri 20 Nov, 11:59 PM | Registration closes (done) |
| Mon 23 Nov, 7:00 PM | Live kickoff, Google Meet (link TBA) |
| Mon 23 – Sat 28 Nov | Build week, help via WhatsApp |
| Sat 28 Nov, 11:59 PM | **Submissions close** |
| Sun 29 Nov, 8:00 PM | Results announced |

## Task

Take a small open-weight Qwen model and do at least one of:

- Fine-tune with LoRA / QLoRA for a specific task
- Quantize so it runs well on everyday hardware
- Run locally (llama.cpp, Ollama, MLX, vLLM)

Then build a small demo showing it doing something useful. No training from scratch.

## Rules

- Solo or team of up to 3
- Any small open-weight Qwen model; follow its license
- **Build during the hackathon week. Older projects do not qualify.** Keep this work in its own fresh effort; do not reuse earlier FYP assets (plans, datasets, results) as the submission.
- Only use datasets we are allowed to use. No private or personal data.
- Judges' decisions are final
- Winners need a free ModelScope account to receive credits

## Submission checklist

- [ ] Model weights or adapter (plus quantized version if made) published on ModelScope or Hugging Face
- [ ] Public GitHub repo with README covering: base model, data, method, hardware, before/after results
- [ ] 2–3 minute demo video of the model running locally

## Judging criteria

1. **Usefulness** – solves a real problem
2. **Technical work** – fine-tuning / quantization done properly
3. **Measured results** – before/after numbers, not vibes
4. **Runs locally** – performance on modest hardware
5. **Write-up and demo** – others can understand and reproduce

## Our idea

Urdu / Roman-Urdu (Urdish) customer-support assistant for a niche business.

- Base: Qwen3 small (4B primary, 1.7B comparison)
- Data: synthetic Urdish support chats for one niche business (no real customer data)
- Method: QLoRA (Unsloth), then GGUF quantization (Q4_K_M, Q8)
- Runtime: llama.cpp / Ollama
- Hardware: RTX 5070 12 GB (WSL2) for training; laptop for the local demo

### Metrics to report (base vs LoRA vs quantized)

- Urdu / Roman-Urdu response quality (judge score, rubric-based)
- Task accuracy on a held-out set
- Tokens/sec, VRAM / RAM use, model size on disk
- Quality drop from quantization (fp16 vs Q8 vs Q4)

### Plan

| Day | Work |
|---|---|
| Mon 23 | Kickoff, repo setup, pick niche, start dataset |
| Tue 24 | Finish dataset, train/val/test split, baseline eval |
| Wed 25 | QLoRA 4B (and 1.7B) |
| Thu 26 | Merge, GGUF convert, eval all variants |
| Fri 27 | Ollama demo, record video, write README |
| Sat 28 | Publish weights, final check, submit before 11:59 PM |

## Prep (setup only, before build week)

- [ ] WSL2 + CUDA works on RTX 5070
- [ ] Unsloth, llama.cpp, Ollama installed
- [ ] Hugging Face and ModelScope accounts
- [ ] Join Qwen Pakistan WhatsApp group
- [ ] Decide solo or team
- [ ] Pick business niche
