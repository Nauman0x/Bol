# Fine-tuning result (Phase 5 compressed): Qwen2.5-7B-Instruct, QLoRA, base vs tuned

**Setup.** Same pre-quantised nf4 base (`unsloth/Qwen2.5-7B-Instruct-bnb-4bit`) with the LoRA adapter off (base) and on (tuned), greedy decoding, same system prompt. LoRA r=16 on all linear layers (40.4M trainable params, 0.53%), 3 epochs on 120 examples (90 steps, final loss about 0.3), lr 2e-4. Train data: `data/sft/train.jsonl` (hand-written, all `synthetic`). Held-out: `data/sft/eval_40.jsonl` (40 new turns, never trained on). Judged blind and shuffled in-session in a 110-item mix (key in `data/work/eval_judge/key_do_not_open.json`).

| Set | Overall (1-5) [95% CI] | understood / register / tone / faithful |
|---|---|---|
| Held-out eval40, **base** | 2.44 [2.18, 2.71] | 2.2 / 2.3 / 2.7 / 2.6 |
| Held-out eval40, **tuned** | **3.95** [3.65, 4.22] | 3.8 / 3.9 / 4.2 / 3.9 |
| Bake-off probe30, tuned | 4.11 [3.76, 4.42] | 4.0 / 4.0 / 4.2 / 4.2 |
| (Phase 1) probe30, base Q4_K_M | 2.98 [2.67, 3.28] | different quantisation, different judging round |

Hard rules on the tuned model: replies under 35 words 100%, no markup 100%, Roman-only 100%, digits spoken 100% (base: digits spoken 97%).

## What improved / what did not
- Biggest gains: orders (1.8 to 4.6), emergency (1.9 to 4.3), lab (1.5 to 3.4), booking (1.9 to 3.4), medical-advice refusals (2.3 to 4.4).
- Still weak (tuned, eval40): phone-number readback (3.1; digits misread on 3 of 6 attempts), payment (3.1), negotiation (3.3), info (3.3).
- Remaining failures seen: invented facts (a made-up JazzCash number, "Bahria Town delivery ok", "free naan"), wrong arithmetic on multi-item totals, Dr Imran offered on Friday, and one **emergency (child choking) answered with an appointment offer**. Not safe to deploy without more data and an emergency-keyword guard.

## Caveats (read before quoting the numbers)
1. Train and eval data are synthetic and written by the same model that judged them; the eval phrasing is close to the training phrasing. The gain is partly learning the two demo businesses' facts. Treat it as in-domain, not general Urdish.
2. One judge, one blind pass, n=40. CIs are bootstrap over items only.
3. Tuned model evaluated on nf4 weights; serving it on the Q4_K_M GGUF (adapter converted) is a different 4-bit form. Latency of the tuned model is **not yet measured**.
4. Closed-platform arm, per-client adapters and real data were dropped to fit the week.
