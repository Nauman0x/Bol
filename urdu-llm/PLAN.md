# BOL Urdu LLM — Implementation Plan (Phase 8)

> **For the executing model (Claude Code running on the user's training PC):** Work through the phases in order. Every phase ends with acceptance criteria — verify them before moving on. Do not substitute decided choices without asking. Where an account/key is needed (Anthropic API, Hugging Face), stub with env vars and tell the user exactly what to create — never hardcode credentials. **Verify library/version facts against the installed package or its docs before writing against them; nothing here about versions or throughput has been measured yet — numbers marked "target" or "estimate" are hypotheses to test.**

## 0. Context you cannot infer from the repo

- **Project**: BOL is an FYP (final-year project), **non-commercial for now**. Platform docs: `bol/docs/PLAN.md` (phases 0–7), `bol/docs/architecture.md`, `bol/docs/LATENCY.md`, `bol/docs/fyp-proposal.md`. Read `LATENCY.md` first — it is the latency baseline and the budget this phase must fit into.
- **Hardware**: desktop PC, **RTX 5070 (12 GB VRAM, Blackwell / sm_120)**, Windows 11 + **WSL2 Ubuntu**. `urdu-tts/` was trained on this machine; read its README "notes" — RTX 50xx needs recent torch/CUDA builds and some libs (e.g. torchaudio) lacked wheels. Expect the same class of problem for training/serving libs. The user also uses a laptop (no training GPU) for scripting only.
- **What we are building**: an Urdu LLM for the voice pipeline (STT → **LLM** → TTS), replacing Groq-hosted Qwen3 as the live LLM. The TTS stage (Piper, Urdu script) is already trained in `urdu-tts/`.
- **Decisions already made (do not re-litigate):**
  1. **Base model: Qalb-1.0-8B-Instruct** (`enstazao/Qalb-1.0-8B-Instruct` on Hugging Face; Llama-3.1-8B-based, continued-pretrained on ~1.84B Urdu tokens, then SFT on Alif Urdu-Instruct). Verify repo, licence and files first. Qwen3 on Groq is the **baseline to beat, not a model we train** (an optional Qwen-8B-base bake-off is Phase 1's decision gate only if Qalb fails the tokenizer/latency gate).
  2. **No RAG.** RAG supplies facts but not delivery. Per-client behaviour **and** facts are learned by fine-tuning on (a) the client's business info turned into dialogues and (b) their past customer ↔ human-agent conversations. Small volatile facts may live in the system prompt as plain text (that is context, not retrieval).
  3. **Output script: Urdu (Nastaliq) script only**, because the Piper voice is trained on Urdu script. Loanwords (اپائنٹمنٹ، آرڈر) are written in Urdu script. Digits/amounts are spelled out as words in the way an Urdu speaker says them. No markdown, no emoji, no Latin text, no lists.
  4. **Three layers**: Qalb base → shared **persona LoRA** (spoken Pakistani phone register) → **per-client LoRA adapter**.
  5. **Real client data is not in hand yet.** First try to obtain a real partner business (Phase 2a). Failing that, build two **synthetic demo clients** (suggest: a clinic and a restaurant), each with a business-info sheet and ~200–400 synthetic "past human-agent" calls. Every report must state this as a limitation.
- **Primary objective: latency.** The LLM stage must be as fast as possible without wrecking quality. This plan is organised around it (see §1).

## 1. Metrics and targets

All metrics are logged per turn so claims are numbers, not impressions. Targets are hypotheses; revise them from Phase 1 measurements, and record the revision.

### 1.1 Latency (the headline)

| Metric | Definition | Target (single stream) |
|---|---|---|
| **TTFT** | request sent → first token received | p50 ≤ 80 ms, p95 ≤ 150 ms |
| **TTFS** (time to first speakable chunk) | request sent → first clause ending in `،` `۔` `؟` `!` or ≥ N chars, i.e. when TTS can start | p50 ≤ 250 ms, p95 ≤ 400 ms |
| Decode speed | tokens/s after the first token | ≥ 60 tok/s |
| Reply length | tokens and words per reply | ≤ ~40 words, ≤ 2 sentences typical |
| Prompt (prefill) tokens | system prompt + history | ≤ 300 tokens system prompt (client facts live in weights, not prompt) |
| Urdu tokenizer fertility | tokens per Urdu word | measure; drives everything above |
| Concurrency | TTFT/TTFS p95 at 1, 2, 4 simultaneous streams | degrade gracefully; record the knee |
| VRAM | peak, with KV cache at the chosen `max_model_len` | ≤ ~9 GB, leaving headroom |
| **End-to-end** | existing `e2e_latency` logged by `worker/agent.py` → `call_events` | LLM share of the ~0.5 s budget in `LATENCY.md` ≤ ~25% |

**Honest framing for the report (do not overclaim):** `LATENCY.md` shows Groq's 368 ms TTFT was ~100% network round trip, ~0% compute. A local model co-located with the worker removes that network hop, so TTFT/TTFS can beat hosted Groq. Groq's raw decode throughput is likely higher than a local 8B on a 12 GB card, so we do **not** claim to out-decode it. We win on: no network hop, tiny prompt (client knowledge is in the weights), short trained replies, short first clause, prefix caching, warm server. **Always benchmark Groq from the same machine and network as the local model**, same prompts, and report both with and without network.

### 1.2 Quality

| Metric | How |
|---|---|
| Urdu fluency / naturalness (spoken Pakistani register) | Claude-as-judge, rubric, pairwise; plus the user's own review of a sample (the user is the native-speaker ground truth) |
| Style fidelity to client | style-statistics distance (reply length, formality markers, characteristic phrases, greeting/closing) between model output and the client's held-out human-agent replies; plus judge win-rate |
| Fact accuracy | closed-book QA set per client with known answers; hallucination rate |
| Tool-call accuracy | BOL agents use function tools (`end_call`, `transfer_call`, webhook tools — see `bol/docs/PLAN.md` Phase 4). Fine-tuning must **not break tool calling**: format validity + argument accuracy on a held-out set |
| TTS-safety | % of replies containing digits, Latin letters, markdown, emoji, or lists (target ≈ 0%) |
| Brevity / spoken-ness | words per reply, sentences per reply |
| General Urdu regression | small held-out Urdu QA / instruction check on Qalb before vs after, to detect catastrophic forgetting |

### 1.3 Experiment conditions (the research result)

A. Qwen3 on Groq, prompt-only (today's system) · B. Qalb, prompt-only · C. Qalb + persona LoRA · D. Qalb + persona + client adapter. Also run D at several client-data sizes (e.g. 25 / 50 / 100 / 200 / 400 conversations) to find the break-even point (proposal RQ4). The proposal's RAG/hybrid conditions are **dropped** — update `bol/docs/fyp-proposal.md` in Phase 9.

## 2. Skills and tooling

**Claude Code skills to use (invoke via the Skill tool; confirm they are installed on the PC):**

| Skill | Use it for |
|---|---|
| `claude-api` | Synthetic data generation and the LLM judge. Read before writing any Anthropic API code; use current model ids from it (bulk generation on a cheaper tier, judging on the strongest). Needs `ANTHROPIC_API_KEY` from the user |
| `engineering:architecture` | One ADR each: base model choice; merged-adapter vs multi-LoRA serving; serving engine |
| `engineering:system-design` | Serving topology: worker ↔ local LLM server, adapter routing, warmup |
| `engineering:testing-strategy` | Eval harness design; regression tests for the data pipeline (anonymiser, formatter, TTS-safety filter) |
| `engineering:debug` | Blackwell/CUDA/WSL2 install failures and OOMs — structured debugging, don't thrash |
| `engineering:documentation` | `urdu-llm/README.md` in the same style as `urdu-tts/README.md`; setup/run steps the user can replay |
| `dataviz` | Charts for the report (latency CDFs, TTFT/TTFS by lever, win-rates). Read it before writing chart code |
| `code-review` / `simplify` | Before each phase commit |
| `run` | Launching the BOL worker to verify the integration end-to-end |
| `deep-research` | Only if a licence/benchmark question needs multi-source research |

**GitHub / open-source tooling (verify current versions and RTX 50xx support before installing):**

- **Unsloth** (QLoRA SFT, fast + low VRAM) with **TRL** `SFTTrainer`; fallback to plain **PEFT + bitsandbytes + TRL** if Unsloth lacks sm_120 support.
- **vLLM** (primary serving: OpenAI-compatible API, automatic prefix caching, multi-LoRA, speculative decoding, FP8/AWQ). Fallbacks: **SGLang**, **llama.cpp** (`llama-server`, GGUF, `llama-bench`) — llama.cpp is the lowest-friction path on consumer Blackwell if vLLM wheels lag.
- **vLLM `benchmark_serving`** or **GuideLLM** for latency/throughput; our own streaming TTFT/TTFS script (custom, since TTFS is not a stock metric).
- **lm-evaluation-harness** only for the general-Urdu regression check; everything else is the custom harness.
- Anonymisation: regex + a lightweight NER pass; Urdu phone/CNIC/address patterns need custom rules (no off-the-shelf Urdu PII tool assumed).

## 3. Repo layout (target)

```
urdu-llm/
├── README.md                 # replayable setup/run, written like urdu-tts/README.md
├── PLAN.md                   # this file
├── setup_wsl.sh              # env + GPU checks
├── configs/                  # train + serve configs (yaml)
├── data/
│   ├── clients/<id>/         # business_info.md, raw_calls/, processed/
│   ├── persona/              # generated shared dialogues
│   └── eval/                 # held-out sets (NEVER used for training)
├── scripts/
│   ├── gen_persona.py        # synthetic phone dialogues (Claude API)
│   ├── gen_client.py         # demo clients: business sheet + past human-agent calls
│   ├── anonymise.py
│   ├── build_sft.py          # transcripts + business info -> chat-format SFT jsonl
│   ├── style_stats.py        # per-client style features
│   ├── train_lora.py         # persona + client adapters
│   ├── merge_adapter.py
│   ├── bench_latency.py      # TTFT/TTFS/decode/concurrency
│   ├── eval_quality.py       # judge + fact QA + tool-call + TTS-safety
│   └── serve.sh              # launch the chosen server
├── tests/                    # pytest: anonymiser, formatter, TTS-safety filter
├── adapters/                 # outputs (gitignore weights; track configs + metrics)
└── report/                   # results, charts, tables (like urdu-tts/report)
```

Large artefacts (weights, adapters, raw audio) are **gitignored or Git LFS** — follow how `urdu-tts` handled its models (LFS).

## Phase 1 — Environment + model gate (do this BEFORE any training)

1. WSL2 Ubuntu, verify `nvidia-smi` sees the RTX 5070. Create a venv; install a torch build that supports sm_120 (CUDA ≥ 12.8). Install Unsloth/TRL/PEFT and vLLM (or llama.cpp). Record exact versions in `README.md`. Fix problems with the `engineering:debug` skill.
2. Download Qalb-1.0-8B-Instruct. **Record its licence and the Llama-3.1 licence terms** in `README.md` (non-commercial FYP use is fine; note the implications for commercial use later).
3. **Tokenizer fertility**: measure tokens/word for Qalb on a sample of Urdu phone-style sentences. Llama-3.1's tokenizer may be inefficient for Urdu; high fertility directly inflates TTFS and decode time. Record it. Also measure Qwen3-8B's tokenizer on the same sentences for reference.
4. **Raw latency floor, no training yet**: serve base Qalb in 2–3 forms (e.g. vLLM AWQ-int4, vLLM FP8 if supported on this GPU, llama.cpp Q4_K_M/Q5) and run `bench_latency.py` with a ~300-token Urdu prompt and ~40-word replies. Record TTFT, TTFS, decode tok/s, VRAM, at 1/2/4 concurrency. Also benchmark Groq Qwen3 from this same machine for the baseline.
5. **Decision gate.** If Qalb's fertility or raw latency makes the §1.1 targets clearly unreachable, stop and present the data to the user with options (a Qwen-8B-class base with Urdu SFT; a smaller Urdu-capable model; token-efficiency work). If it is workable, record the chosen quantization + engine in an ADR and continue.

**Accept:** `nvidia-smi` OK; base Qalb generates sensible Urdu through the chosen server; fertility + raw-latency table committed to `report/`; ADR written; user has seen the gate result.

## Phase 2a — Data sourcing (real data first, synthetic as augmentation)

**Finding (searched Nov 2026):** no free, public Urdu call-center or support-chat corpus was found. Commercial sets exist (Shaip, Appen, Macgence — licensed, not affordable for an FYP). Re-check Hugging Face / OpenSLR yourself before assuming this still holds. **None of the sources below was opened or licence-checked — verify each before use and record the licence in `data/SOURCES.md`.**

Sources, in order of preference:

1. **Real partner business (preferred, strongest result).** The user asks 1–2 Pakistani businesses they know (clinic, salon, restaurant, shop) for ~50–400 past customer ↔ human-agent conversations (WhatsApp/chat exports or call transcripts) plus a business-info sheet, **with the owner's written consent** and used only for this FYP. Anonymise before anything is stored in the repo (Phase 3 `anonymise.py`); raw exports stay outside git. **Ask the user whether they have such a contact — do not fabricate "real" data.** If transcripts are audio, transcribe with Whisper large-v3 and have the user spot-check.
2. **Public real Urdu speech/chat for the persona layer (register reference, not business content):**
   - Nexdata *Urdu Conversational Speech Data by Telephone* (HF `Nexdata/Urdu_Conversational_Speech_Data_by_Telephone`) — telephone speech sample; check it has transcripts and what the licence allows.
   - `mwz/UrduAssistant` (HF, MIT) — Urdu query↔reply pairs; written chat, not phone/task-oriented.
   - Alif Urdu-Instruct, Urdu Alpaca Filtered, Dolly Urdu (see the Traversaal `urdu-llm-resources` registry) — general Urdu instruction data, optional mix-in to protect general Urdu ability.
   - Roman-Urdu chat corpora exist but are Roman script and sentiment-labelled; not used for training (our output is Urdu script). May inform code-switching vocabulary only.
3. **Claude-generated dialogues (Phases 2–3) are augmentation, not the foundation.** Whenever real transcripts exist (source 1 or 2), feed a sample of them as few-shot style references in the generator prompts so synthetic phrasing copies real phrasing. Tag every example with a `source` field (`real_partner` / `real_public` / `synthetic`) so training mixes and eval slices can be reported by source.
4. **BOL's own test calls** (real people talking to the agent) — once the system runs, transcripts of tester calls can be added as `real_testcall` data. Real speech, but not real customers; label accordingly.

**Scope decision (user, Nov 2026): most Pakistani SMBs keep no call recordings or text logs, so "train on your past conversations" cannot be the only input.** For the FYP we build and test the **customization layer** — a pipeline that turns a small *client onboarding package* into a client adapter — using demo clients. Real-client onboarding (owner questionnaire, staff role-play sessions, WhatsApp exports, post-launch flywheel from BOL `call_events`) is **documented as the proposed commercial onboarding process and future work, not built or validated now.** Past logs are an *optional* richer input when they exist.

The **client onboarding package** (defined in Phase 3; this is the layer's input contract), in increasing richness — the pipeline must work at every level, and the experiment measures each:
- **L0** business-info sheet only (no examples) → synthetic dialogues from the sheet
- **L1** sheet + 15–30 owner-style seed Q&A examples (how *we* would answer) — the realistic cold start
- **L2** sheet + 20–40 role-play-style conversations (staff phrasing)
- **L3** sheet + real past conversations (chat exports / transcripts), when available

**Rules:** the eval set for any client must be drawn from its *real* conversations if they exist (never synthetic-only), and never overlaps training. If no partner business materialises, proceed with synthetic demo clients and state the limitation prominently in the report. Never present synthetic data as real.

**Accept:** `data/SOURCES.md` lists every source with licence and verified status; the user has answered whether a real partner business is available; every dataset record carries a `source` tag.

## Phase 2 — Data: persona layer (shared)

1. `gen_persona.py` generates a few thousand synthetic Urdu phone dialogues across scenarios (appointments, orders, complaints, pricing questions, callbacks, wrong number, angry caller, hold/transfer requests, goodbye). Use the `claude-api` skill. Prompt the generator for **spoken** Pakistani Urdu: polite forms (جی، آپ، شکریہ)، natural fillers, short turns, Urdu-script loanwords, spelled-out numbers, no markdown.
2. **Latency-shaped replies** (deliberate): train agent replies to (a) be short (≈ 1–2 sentences), and (b) when appropriate **open with a short natural acknowledgement clause** ("جی بالکل،" / "ٹھیک ہے،") so the first speakable chunk is a few tokens and TTS can start almost immediately.
3. Include **tool-call turns** in the BOL tool schema so function calling survives fine-tuning (end_call, transfer_call, one generic webhook example).
4. A **TTS-safety filter** (`tests/`) rejects samples with digits, Latin, markdown, emoji, lists. Reject and regenerate.
5. Split by *scenario*, not by random turn, into train / val / test. `data/eval/` is frozen and never trained on.
6. **Stop and ask the user to read ~50 samples** and mark unnatural phrasing. Feed their notes back into the generator prompt. The user is the native-speaker ground truth; do not skip this.

**Accept:** ≥ 3k filtered dialogues, TTS-safety pass-rate 100% after filtering, user-reviewed sample approved, eval set frozen.

## Phase 3 — Data: demo clients + the per-client pipeline

0. **Define the onboarding package** (the customization layer's input contract) as a schema + folder spec in `urdu-llm/docs/ONBOARDING.md`: `business_info.md` (fixed sections: services, prices, hours, policies, FAQs, brand tone, handoff rules), optional `seed_examples.jsonl` (L1), optional `roleplay/` (L2), optional `raw_calls/` (L3). One command — `build_client.py <client_dir>` — runs anonymise → generate/expand → format → train → evaluate and produces an adapter plus a metrics report. This command *is* the product of this phase; keep it generic, with no per-client code.
1. **For each level, create demo inputs** (L0–L2 from `gen_client.py` plus hand-written seed examples by the user; L3 only if a real partner exists, per Phase 2a). `gen_client.py` creates two demo clients (clinic, restaurant): a `business_info.md` (services, prices, hours, policies, FAQs, brand tone) and ~200–400 synthetic past customer ↔ human-agent calls in that client's voice, with realistic imperfections (agent-specific phrasing, local idioms, occasional hold/transfer).
2. `anonymise.py` removes names, phone numbers, CNIC, addresses, payment details (regex + NER). Unit-test it.
3. `build_sft.py` turns each client's data into SFT examples: (a) the human agent's turns are the targets in their real conversations; (b) **business-info → dialogue** generation so facts are *learned* (since there is no RAG) — varied questions about each service/price/policy/hour with the client's phrasing; (c) negative/safety examples: politely decline or hand off when the answer is not known, rather than invent a fact.
4. `style_stats.py` computes per-client style features (also feeds the proposal's style-profile idea and the style-fidelity metric).
5. Hold out 20% of each client's conversations and a closed-book fact-QA set for eval.

**Accept:** pipeline runs end-to-end on both demo clients with one command; unit tests green; held-out sets frozen; user reviewed a sample per client.

## Phase 4 — Train the persona LoRA

- QLoRA (4-bit NF4 base) on Qalb. Starting points, to be swept and justified, not assumed: rank 16/32/64, alpha = 2×rank, all attention + MLP projections, lr ~1e-4–2e-4 cosine, 2–3 epochs, **short max sequence length** (phone dialogues are short — this also keeps training fast), gradient checkpointing, batch via accumulation to fit 12 GB.
- Log train/val loss; stop on val loss; save the best adapter.
- Re-run the **general-Urdu regression** check (no big drop) and the **tool-call** check.
- Re-measure latency of base+LoRA (unmerged) vs merged — record the delta.

**Accept:** val loss converged; persona judge win-rate over base-Qalb-prompt-only is positive with the sample of numbers recorded; no meaningful general-Urdu regression; tool-call accuracy preserved.

## Phase 5 — Train per-client adapters

- Train each client LoRA **on top of the persona-merged weights** (or stacked — decide in an ADR based on Phase 4 measurements and the serving choice). Keep per-client training short: record wall-clock minutes and VRAM per client — "retrain cheaply when business info changes" is a product claim and needs the number.
- **Onboarding-level sweep**: train and evaluate each demo client at L0, L1 (e.g. 10/25 seed examples), L2, and L3 if available. The question: how few seed examples before the adapter beats prompt-only Qalb on style, facts and latency? Optionally also sweep total training dialogues (25/50/100/200/400).
- **Hand-written seeds matter:** the user writes (or dictates) the L1 seed examples for the demo clients, so at least some "client voice" is genuinely human. Ask the user to do this; do not substitute generated seeds silently — if generated seeds are used, tag them `synthetic`.
- Verify facts are actually learned (closed-book QA) and that unknown-info cases hand off rather than hallucinate.

**Accept:** two client adapters; closed-book fact accuracy and style-fidelity measured vs conditions A–C; sweep curve produced.

## Phase 6 — Latency optimisation (the differentiator)

Treat each lever as an experiment: change one thing, re-run `bench_latency.py`, record TTFT / TTFS / decode / VRAM delta and any quality delta. Do not adopt a lever that costs quality without recording it.

1. **Quantization**: compare FP16 vs AWQ/GPTQ int4 vs FP8 (Blackwell supports low-precision formats — verify engine support) vs GGUF. Measure quality drop with the judge, not just speed.
2. **Prefix caching**: enable it; keep the system prompt byte-identical across turns and short (≤ ~300 tokens) so the cached prefix is reused. Confirm hit rate.
3. **Server tuning**: small `max_model_len` (phone calls are short), limited `max_num_seqs`, CUDA graphs on, chunked prefill settings, warmup request at startup, pinned/warm adapters.
4. **Adapter strategy**: merged single-client weights (fastest, one model per client in VRAM) vs multi-LoRA hot-swap (flexible, some overhead). Measure both; the ADR picks per deployment mode — e.g. merged for a dedicated client, multi-LoRA for many.
5. **Speculative decoding**: try n-gram/prompt-lookup and a small draft model; keep only if net TTFS/decode gain at our reply lengths.
6. **Reply shaping**: confirm the trained short-opener behaviour actually lowers TTFS; try tightening max tokens and a stop on the first sentence boundary configuration at the TTS side if safe.
7. **Streaming boundary**: verify the worker hands the first clause to Piper TTS as soon as it appears (the livekit-agents LLM→TTS stream); measure clause-to-first-audio.
8. **Tokenizer-level (only if Phase 1 flagged high fertility)**: consider whether common Urdu phone vocabulary can be made cheaper — but do not start vocabulary surgery without telling the user; it is risky and probably out of FYP scope. Document as future work otherwise.

**Accept:** a lever-by-lever table with before/after numbers; final configuration meets or honestly misses §1.1 targets, with the reason documented; p95 under 1/2/4 concurrency recorded.

## Phase 7 — Evaluation (quality + latency together)

- `eval_quality.py` runs conditions A–D (+ sweep) over the frozen held-out sets: judge pairwise (rubric, randomised order, position-swapped to avoid bias), style distance, closed-book fact accuracy, tool-call accuracy, TTS-safety, brevity.
- `bench_latency.py` runs the same prompts against Groq Qwen3 (from this machine) and the final local config. Report with and without network.
- Add a quality-vs-latency view: the claim is "comparable or better Urdu/style quality at lower and more stable TTFS", not "better at everything".
- Produce charts via the `dataviz` skill into `report/`, plus a short results summary like `urdu-tts/report/SUMMARY.md`.

**Accept:** results tables + charts committed; the break-even data-size curve; a candid limitations section (synthetic data, single judge family, one GPU, small client count).

## Phase 8 — Integration into BOL

- `bol/backend/worker/pipeline.py`: add `LLM_PROVIDER=groq|local` (env), mirroring `STT_PROVIDER`/`TTS_PROVIDER`. For `local`, use livekit-agents' OpenAI-compatible LLM plugin pointed at the local server's `base_url`; **verify the installed livekit-agents/plugin API**, don't trust memory. Keep `groq` as the fallback and as the baseline.
- Per-agent/org adapter selection: the agent's config names the client adapter (server routes by model/LoRA name). Do not break existing agents (regression test like `test_pipeline.py`'s lock test).
- Log LLM TTFT/TTFS and the `local` flag into `call_events` `payload.timings` alongside the existing metrics, so live calls produce the same numbers as the benchmark.
- Add the LLM server to `docker-compose` behind a `gpu` profile (see Phase 6 of `bol/docs/PLAN.md`) and document that the worker and LLM server should be co-located.
- Test with a real call or the LiveKit Agents Playground (browser mic) using the `run` skill. Compare the logged `e2e_latency` against the `LATENCY.md` baseline.

**Accept:** a voice conversation in Urdu works end-to-end through STT → local LLM (client adapter) → Piper; per-turn latency numbers appear in `call_events`; Groq fallback still works.

## Phase 9 — Documentation and proposal update

- `urdu-llm/README.md`: replayable setup, data pipeline, training, serving, benchmarking.
- Update `bol/docs/fyp-proposal.md` §6 and the research questions: remove RAG/hybrid; replace with prompt-only vs persona vs persona+client-adapter, add the latency contribution and the onboarding-level break-even finding (RQ4: with how few seed examples does the adapter win?).
- Add a **"Commercial onboarding (proposed, not validated)"** section: owner questionnaire + 15–30 seed examples, staff role-play session, optional WhatsApp export, then a post-launch flywheel (BOL `call_events` → human review → retrain). Present it as future work, since SMBs typically keep no logs.
- Update `bol/docs/architecture.md` (the row that says "LLM fine-tuning / personalization: No" becomes "Yes") and `bol/docs/LATENCY.md` with the measured local-LLM numbers.

## Execution notes

- Commit at the end of each phase with a message naming the phase. Run `code-review`/`simplify` first.
- Never train on `data/eval/`. Never log or commit real customer data; demo data is synthetic and labelled so.
- Ask the user before: spending significant Anthropic API budget (estimate token cost first), vocabulary/tokenizer changes, or abandoning Qalb at the Phase 1 gate.
- Keep GPU sessions resumable (checkpoints), as in `urdu-tts` — training and serving share one 12 GB card, so stop the server before training.
- If a number comes out worse than the target, report it plainly; an honest negative is a valid FYP result.
