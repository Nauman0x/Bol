# BOL Urdu LLM — Implementation Plan (FYP-I model layer)

> **For the executing model (Claude Code running on the user's training PC):** Work through the phases in order. Every phase ends with acceptance criteria — verify them before moving on. **No Anthropic API key is used (user decision): all Claude-assisted work — generation and judging — runs in-session, see "In-session generation and judging protocol" below.** Where an account/key is needed (Hugging Face, closed-platform accounts, Groq for the optional reference arm), stub with env vars and tell the user exactly what to create — never hardcode credentials. **Verify library/version facts against the installed package or its docs; nothing here about throughput, versions or licences has been measured or checked yet — numbers marked "target" or "estimate" are hypotheses to test, and every dataset/model licence must be read, not assumed.**

## 0. Ultimate goal and context

**The goal is FYP-I, and giving it our best.** The user's instruction: *the submitted proposal may diverge in details; the model choice does not matter; what matters is the FYP-I outcome, delivered as strongly as possible.* Decide on evidence, not attachment to any model named below, and record each deviation from the submitted proposal in `report/DEVIATIONS.md` (the user will explain them to supervisors).

**FYP-I outcome (from the submitted proposal "Project Bol: An Open, Culturally-Tuned Voice AI Stack for Pakistani Businesses"):** "construct a consented Pakistani-speech evaluation set and Roman-Urdu dialogue corpus, quantify the failure modes of closed voice platforms against both a prompting-only and a fine-tuned open stack, and demonstrate measurable error reduction on those modes through QLoRA fine-tuning of an open 7–8B model and fine-tuning of Whisper on Pakistani speech." Organising thesis: *culture lives in weights, tasks live in prompts.* The proposal's rules this plan must respect:

- **Three-arm benchmark** on identical material: **A** closed platforms (Retell/VAPI) as deployed for a client · **B** open stack, prompting only (the load-bearing control; A≈B is a finding, not a failure) · **C** open stack, fine-tuned.
- **Failure taxonomy first, and it gates scope: "no taxonomy tag, no fine-tune."** Named modes include phone-number transcription, code-switch boundary errors, honorific flattening, negotiation handling. A fine-tune must target a tagged, quantified failure mode.
- **Eval set is held out and never trained on.** Metrics: WER (weighted to digits/phone numbers), task completion, blind MOS naturalness with human-agent reference recordings as the ceiling, latency, cost per minute. Claims scoped to what the metrics measure. Significance testing (SciPy/scikit-learn).
- **Consent and PII:** written consent before any recording is collected or committed; PII (names, phone numbers, addresses) stripped by an **on-device** format-preserving redaction pass before any transcript enters training; no identifying data leaves the team's infrastructure.
- **Only commercially licensable checkpoints** (proposal scope exclusion). Check the licence of every base model and every dataset used for training; record in `data/SOURCES.md`.
- **One core model; per-tenant adapters are gated deltas on it, never forks.**
- **Excluded in FYP-I by the proposal:** real-time streaming telephony, a self-serve onboarding engine, full-duplex interruption handling, Punjabi/Saraiki/Pashto, >70B training. The per-client pipeline here is a **CLI pipeline, not a self-serve engine**.

**Hardware (differs from the proposal's 24 GB):** user's desktop PC, **RTX 5070 12 GB (Blackwell, sm_120)**, Windows 11 + **WSL2 Ubuntu**. Update the proposal's compute line. `urdu-tts/` was trained on this machine — read its README notes: RTX 50xx needs recent torch/CUDA builds and some libs lacked wheels; expect the same class of problem. Use short sequence lengths; 7–8B QLoRA should fit but verify. Cloud GPU hours are the fallback for anything that does not. The user also uses a laptop (no training GPU) for scripting.

**Decisions made (reasoned; revisit only with measured evidence):**
1. **Base model = bake-off winner (Phase 1).** Candidates: **Qwen2.5-7B-Instruct** (proposal's choice), **Qwen3-8B**, **Qalb-1.0-8B-Instruct** (`enstazao/Qalb-1.0-8B-Instruct`, Llama-3.1-based, continued-pretrained on ~1.84B Urdu tokens; strong Urdu *script* prior, Roman-Urdu skill unknown). Default to Qwen2.5-7B if no candidate clearly wins. Eligibility: commercially usable licence.
2. **Primary language track = Roman-Urdu / Urdish** (matches the proposal's dataset, the eval set, Whisper's fine-tune target and "culture-flat" failure framing: e.g. "bhai 2 large fajita bhejdo gol masjid k pas"). **Urdu-script** is measured in the bake-off and kept as a secondary variant. Piper (`urdu-tts/`) reads Urdu script, so a **Roman→Urdu-script converter** (`scripts/translit.py`, dictionary + rules first; English loanwords are a known gap) sits between LLM and TTS; its latency and error rate are measured, not assumed. The converter is optional for FYP-I's text-level results.
3. **No RAG.** Facts and delivery are learned into the adapter from business-info dialogues. In Arm B (prompt-only) the same business facts and style instructions are placed in the system prompt — the strongest honest prompt we can write — so the control is fair. Small volatile facts may also sit in the system prompt of the adapter model (context, not retrieval). Deviation from the proposal's "facts live in retrieval" → log in `DEVIATIONS.md`. (If time allows, an Arm "adapter + retrieval" ablation can test it.)
4. **Latency is a first-class goal** (§1.1), not a footnote.
6. **In-session generation and judging protocol (no API key).** Claude Code on the PC writes data and scores outputs itself, in resumable batches:
   - `scripts/` builds a **batch brief** (scenario, business KB, style guide, few-shot real examples, output schema) under `data/work/batches/NNN.brief.md`.
   - The session (or parallel subagents via the Agent tool, ~20–50 dialogues per batch to keep quality and context manageable) writes `NNN.out.jsonl` in that schema; `scripts/` **validates** (schema, TTS-safety, anonymisation, dedup) and merges, rejecting bad rows into a regenerate list. Never hand-merge unvalidated output.
   - **Judging:** `scripts/harness/` exports **blind, shuffled, position-swapped** pairs to `data/work/judge/NNN.in.jsonl`; the session scores against the rubric and writes `NNN.out.jsonl`; arm identity is hidden until unblinding in the scorer. Spot-check agreement with the user's own labels on a sample.
   - Track progress in `data/work/PROGRESS.md` so a session restart resumes at the next batch. Expect the volume to be bounded by the user's Claude Code usage limits: start with ~500 dialogues, check quality with the user, then scale; tell the user the batch count and rough usage before large runs.
   - Quality control matters more than volume: the user reviews samples (Phase 4 step 7) before each scale-up.
5. **Real client data is not in hand.** Most Pakistani SMBs keep no recordings or text logs. FYP-I builds and tests the **customization layer** on demo clients; real onboarding (questionnaire, role-play sessions, WhatsApp exports, post-launch flywheel from BOL `call_events`) is *proposed future work, not validated*.

## 1. Metrics and targets

All metrics are logged per turn/sample so claims are numbers. Targets are hypotheses; revise from Phase 1 measurements and record the revision.

### 1.1 Latency (headline)

| Metric | Definition | Target (single stream) |
|---|---|---|
| **TTFT** | request sent → first token | p50 ≤ 80 ms, p95 ≤ 150 ms |
| **TTFS** (time to first speakable chunk) | request sent → first clause ending `,` `.` `?` `!` `،` `۔` `؟` or ≥ N chars, i.e. when TTS can start | p50 ≤ 250 ms, p95 ≤ 400 ms |
| Decode speed | tokens/s after first token | ≥ 60 tok/s |
| Reply length | tokens and words per reply | ≤ ~40 words, ≤ 2 sentences typical |
| Prompt (prefill) tokens | system prompt + history | ≤ ~300-token system prompt for adapter models (client knowledge in weights) |
| Tokenizer fertility | tokens per word, **Roman-Urdu and Urdu-script separately**, per candidate model | measure; drives all of the above |
| Concurrency | TTFT/TTFS p95 at 1, 2, 4 simultaneous streams | degrade gracefully; record the knee |
| VRAM | peak incl. KV cache at chosen `max_model_len` | ≤ ~9 GB |
| Transliteration step | Roman→Urdu-script latency and error | measure if TTS bridge is used |
| **Cost per minute** | local: GPU power/amortisation estimate; closed platforms: published per-minute price | report both, with assumptions stated |
| **End-to-end** | existing `e2e_latency` in `call_events` (see `bol/docs/LATENCY.md`, ~0.5 s budget) | LLM share ≤ ~25% |

**Honest framing (do not overclaim):** `LATENCY.md` shows Groq's 368 ms TTFT was ~100% network, ~0% compute. A local model co-located with the worker removes the hop, so TTFT/TTFS can beat hosted LLMs. Hosted engines likely out-decode a local 8B on a 12 GB card, so we do not claim raw-throughput superiority. Our edge: no network hop, tiny prompt (knowledge in weights), short trained replies, short first clause, prefix caching, warm server. **Benchmark hosted baselines from the same machine and network, with and without network time.**

### 1.2 Quality and task metrics

| Metric | How |
|---|---|
| **Task completion** (proposal metric) | Offline order/booking scenarios: **scripted caller scripts with branching rules** (written in-session, deterministic and replayable; optionally a local open model plays the caller for variety) drive the agent over text; success = correct slots filled (items, quantity, address/landmark, time) and correct final confirmation. Report rate with CIs |
| **WER** (ASR track, Phase 7) | `jiwer`, with a digit/phone-number-weighted variant; Whisper base vs fine-tuned |
| **Code-switch fidelity** | judge + rule checks: stays in Urdish register, handles English-in-Roman-Urdu without flattening to English |
| **Honorific handling** | judge + rules (aap/tum/tu, jee, sahab) vs the situation; tagged mode in the taxonomy |
| **Negotiation handling** | scenario set (price haggling, discount asks) with rubric |
| **Fact accuracy** | closed-book QA per client with known answers; hallucination rate; correct hand-off when unknown |
| **Style fidelity to client** | style-statistics distance (reply length, formality markers, characteristic phrases, greeting/closing) vs the client's held-out replies, plus judge win-rate |
| **Naturalness (MOS)** | blind listening (TTS-rendered), human-agent reference recordings as the ceiling, ≥ N raters; text-only blind preference as a cheaper proxy |
| Tool-call accuracy | BOL agents call `end_call`, `transfer_call`, webhook tools; fine-tuning must not break tool calling |
| TTS-safety | % of replies with markdown, emoji, lists, or characters the TTS path cannot read (target ≈ 0%) |
| General regression | small held-out general-Urdu/English instruction check before vs after fine-tune (forgetting) |

Judges: pairwise, rubric-based, position-swapped, randomised; judging runs **in-session** (blind batch files scored by Claude Code or subagents, never told which arm produced which output), supplemented by rule-based scorers and a local open-model judge for scale; report judge-vs-human agreement on a hand-labelled sample by the user. State in the report that the judge family is Claude and results were scored in-session. Use bootstrap CIs and significance tests (SciPy/scikit-learn) for every comparison.

### 1.3 Experiment arms

- **A** — closed platforms (Retell, VAPI) built as a client would deploy them, same scenarios (requires the user's paid accounts; **review each platform's terms of service for benchmark traffic first**).
- **A′** (optional reference) — hosted open model (Groq Qwen3) prompt-only.
- **B** — chosen open base model, **prompt-only** (best honest prompt incl. business facts + style guide).
- **C1** — base + persona/core LoRA ("core v1").
- **C2** — core + per-client adapter, swept over onboarding levels L0–L3 (§Phase 5).

Report every arm on every metric, per taxonomy failure mode.

## 2. Skills and tooling

**Claude Code skills (invoke via the Skill tool; confirm installed on the PC):**

| Skill | Use it for |
|---|---|
| *(no `claude-api`)* | Not used: no API key. Generation and judging follow the in-session protocol below |
| `engineering:architecture` | ADRs: base-model choice; script track; merged vs multi-LoRA; serving engine |
| `engineering:system-design` | Benchmark harness and serving topology |
| `engineering:testing-strategy` | Eval harness design; tests for anonymiser, formatter, TTS-safety filter, scorers |
| `engineering:debug` | Blackwell/CUDA/WSL2 failures and OOMs |
| `engineering:documentation` | `urdu-llm/README.md`, `docs/ONBOARDING.md` |
| `dataviz` | Report charts (per-mode error rates by arm, latency CDFs, lever deltas, learning curves) |
| `code-review` / `simplify` | Before each phase commit |
| `run` | Launching the BOL worker for the optional integration check |
| `deep-research` | Related-work sweep (novelty claims must be verified before being asserted), licence questions |

**Step 0 — get the skills (do this first, before Phase 1):**
1. List the skills/plugins available in the PC session (the `Skill` tool listing, `/plugin`, `/skills`). Compare against the table above.
2. For any missing skill, install it: use `/plugin marketplace add <github-owner/repo>` then `/plugin install <name>@<marketplace>` where a marketplace exists, or copy a skill folder (with its `SKILL.md`) into `~/.claude/skills/<name>/`. Ask the user for the exact marketplace/repo if the skill came from them; do not guess URLs.
3. **Search GitHub for additional skills that help this work** — e.g. LLM fine-tuning (Unsloth/TRL/PEFT), vLLM/inference serving and benchmarking, Hugging Face model/dataset/hub workflows, speech/ASR evaluation (Whisper, jiwer), data-labelling/eval-harness helpers. Treat third-party skills as untrusted: **read the full `SKILL.md` and any bundled scripts before installing, prefer well-known maintainers, and tell the user what each one does and where it came from before enabling it.** Skills run instructions with your tool access; never install one that fetches and executes remote code or asks for credentials you have not been given.
4. Record installed skills and sources in `urdu-llm/README.md` ("Skills used"). If a skill is unavailable, proceed without it and say so; do not block.
5. Skills may need a session restart to appear — tell the user if so.

**Open-source tooling (verify versions + RTX 50xx support first):** Unsloth or Axolotl + TRL + PEFT + bitsandbytes (QLoRA); faster-whisper + `jiwer` + Whisper fine-tune scripts (HF Transformers); **vLLM** (primary serving: OpenAI-compatible, prefix caching, multi-LoRA, speculative decoding, FP8/AWQ), **llama.cpp** `llama-server`/`llama-bench` as the low-friction fallback on consumer Blackwell, SGLang optional; GuideLLM or vLLM `benchmark_serving` plus our own streaming TTFT/TTFS script; Label Studio for annotation/taxonomy tagging; `lm-evaluation-harness` for the general-regression check only; SciPy/scikit-learn for stats. Anonymisation: regex + lightweight NER, on-device (OpenMed-style approach); Urdu/Roman phone, CNIC and landmark-address patterns need custom rules.

## 3. Repo layout (target)

```
urdu-llm/
├── README.md                 # replayable setup/run, like urdu-tts/README.md
├── PLAN.md                   # this file
├── setup_wsl.sh
├── configs/                  # train + serve configs
├── docs/ONBOARDING.md        # client onboarding package spec (L0-L3)
├── data/
│   ├── SOURCES.md            # every source: licence, consent status, verified?
│   ├── eval/                 # frozen held-out sets — NEVER trained on
│   ├── dialogues/            # Roman-Urdu task-oriented corpus (source-tagged)
│   └── clients/<id>/         # business_info.md, seed_examples.jsonl, roleplay/, raw_calls/
├── scripts/
│   ├── bench_models.py       # Phase 1 bake-off: fertility + raw latency + quality probe
│   ├── harness/              # arms A/B/C replay, scorers, taxonomy tagging
│   ├── gen_dialogues.py      # Urdish task-oriented dialogues from business KBs
│   ├── gen_client.py         # demo clients
│   ├── anonymise.py
│   ├── build_sft.py
│   ├── style_stats.py
│   ├── build_client.py       # onboarding package -> adapter + metrics (the customization layer)
│   ├── train_lora.py / merge_adapter.py
│   ├── translit.py           # Roman -> Urdu script bridge for Piper
│   ├── whisper_ft/           # Phase 7
│   ├── bench_latency.py
│   └── serve.sh
├── tests/
├── adapters/                 # weights gitignored/LFS; configs + metrics tracked
└── report/                   # results, charts, DEVIATIONS.md, SUMMARY.md
```
Large artefacts are gitignored or Git LFS, as in `urdu-tts`.

## Phase 1 — Environment + model bake-off (before any training)

1. WSL2 Ubuntu; `nvidia-smi` sees the RTX 5070. venv with a torch build supporting sm_120 (CUDA ≥ 12.8); install QLoRA stack and vLLM (or llama.cpp). Record exact versions in `README.md`. Fix problems with `engineering:debug`.
2. Download candidates (Qwen2.5-7B-Instruct, Qwen3-8B, Qalb-1.0-8B-Instruct). **Read and record each licence** (and the Llama-3.1 terms for Qalb) in `data/SOURCES.md`; drop any candidate that is not commercially usable.
3. `bench_models.py` for every candidate: (a) **tokenizer fertility on Roman-Urdu and Urdu-script** phone-style sentences (use a hand-written set of ~100 each — the user supplies/approves them); (b) **raw latency floor** in 2–3 serving forms (e.g. vLLM AWQ-int4, FP8 if supported, llama.cpp Q4_K_M) at ~300-token prompts / ~40-word replies, 1/2/4 concurrency; (c) a **quality probe**: 30 Urdish order/booking turns, judged blind, prompt-only — does the model even understand Urdish, honorifics, code-switching? (d) the same prompts through Groq Qwen3 from this machine as baseline.
4. **Decision gate.** Pick the base model on measured fertility, latency and Urdish quality (ADR). Qwen2.5-7B is the default on a tie. Present the table to the user before moving on. If every candidate misses the §1.1 targets badly, say so and propose options (smaller model, token-efficiency work) — do not silently relax targets.

**Accept:** base model generates sensible Urdish via the chosen server; fertility + raw-latency + quality table in `report/`; ADR written; user has seen the gate result.

## Phase 2 — Consent, PII and sources

1. `data/SOURCES.md` lists every data source with: licence, consent status, verified-by, and a `source` tag value (`real_partner` / `real_public` / `synthetic` / `real_testcall`). Never present synthetic data as real.
2. Consent framework: written consent template for any recording/transcript (voice is biometric); anything real stays outside git until consented and anonymised. The user owns the consent track (a native Urdu speaker on the team owns data + consent).
3. `anonymise.py` (on-device): names, phone numbers, CNIC, addresses/landmarks, payment details, format-preserving replacement. Unit tests with Roman-Urdu and Urdu-script cases.
4. **Public data (search found no free public Urdu call-center corpus; re-check HF/OpenSLR yourself; none of these was opened or licence-checked):** Nexdata *Urdu Conversational Speech Data by Telephone* (HF sample), `mwz/UrduAssistant` (MIT, written chat), Alif Urdu-Instruct / Urdu Alpaca Filtered / Dolly Urdu via the Traversaal `urdu-llm-resources` registry (general instruction data; check the licence and that GPT-4o-generated data is acceptable for the commercial-use rule). Roman-Urdu corpora (UCI, Mendeley RUWV-NSR, HF sentiment corpus) are sentiment-labelled; at most vocabulary/spelling-variant references.
5. **Real partner business** (written consent, 50–400 anonymised chats + business sheet) is the best possible addition. Ask the user whether they have such a contact; never fabricate "real" data.

**Accept:** `SOURCES.md` complete and honest; anonymiser tests green; consent template ready; user has said whether a real partner exists.

## Phase 3 — Benchmark harness, baselines, failure taxonomy (the gate)

1. **Eval material:** the held-out scenarios and (for the ASR track) the Pakistani-speech eval set. The *speech* eval set (50–100 speakers, rolling recording through week 10) is a **human workstream owned by the user**; this plan builds the tooling (recording script lists, transcription QC in Label Studio, WER scoring) but cannot create the recordings. For the LLM harness, build a frozen text scenario set (orders, bookings, phone numbers, landmark addresses, negotiation, honorific situations) in Urdish — written/approved by the user, expanded by Claude, never trained on.
2. **Harness** (`scripts/harness/`): identical scenarios replayed through arms B and C locally (and A/A′ via closed-platform and Groq adapters), logging every output with timings. Closed-platform runs need the user's accounts and a ToS check; stub them behind a clean interface and tell the user exactly what to set up.
3. **Run Arms A, A′ (optional) and B** → first results table.
4. **Failure taxonomy v1:** tag baseline outputs (Label Studio or a script + hand review) into named modes — at minimum phone-number handling, code-switch boundary errors, honorific flattening, negotiation handling, plus any new mode that emerges. Quantify per-mode error rates per arm.
5. **Gate:** "no taxonomy tag, no fine-tune." Write which modes the core fine-tune will target and why; record the decision.

**Accept:** harness replays all arms from one command; first results table and taxonomy v1 with per-mode rates committed; fine-tune targets written down; user has reviewed the taxonomy.

## Phase 4 — Roman-Urdu dialogue dataset (synthetic bootstrap + real refinement)

1. **Generate in-session** (protocol below; `gen_dialogues.py` only builds the batch *briefs* and validates/merges the returned files — it makes no API calls) **task-oriented Urdish dialogues from business knowledge bases** (restaurants, clinics, retail, delivery) across scenarios: orders, bookings, complaints, price/discount negotiation, address-by-landmark, number readouts, callbacks, wrong number, angry caller, hold/transfer, goodbye. Seed prompts with real Roman-Urdu text where available (SOURCES.md) so phrasing copies real usage, not translated English.
2. **Target the taxonomy:** oversample the failure modes the gate selected (e.g. more landmark addresses, phone-number readbacks, honorific shifts, negotiation).
3. **Latency-shaped replies (deliberate):** short (1–2 sentences) and, where natural, an opening acknowledgement clause ("ji bilkul,") so the first speakable chunk is a few tokens and TTS can start almost immediately.
4. Include **tool-call turns** in the BOL tool schema (`end_call`, `transfer_call`, one generic webhook).
5. TTS-safety filter in `tests/`; reject/regenerate offenders. If the TTS bridge is used, also reject text `translit.py` cannot handle.
6. Split by *scenario*, not random turn, into train/val/test. Freeze `data/eval/`.
7. **Ask the user to read ~50 samples** and mark unnatural phrasing; feed notes back into the generator. The user is the native-speaker ground truth.

**Accept:** ≥ 3k filtered dialogues with `source` tags, filters at 100% pass, user-approved sample, eval set frozen and disjoint from training.

## Phase 5 — QLoRA core v1, then the customization layer (client adapters)

**Core v1:** 4-bit NF4 QLoRA on the chosen base, attention + MLP projections, r = 16/32 (sweep, justify), alpha = 2×rank, lr ~1e-4–2e-4 cosine, 2–3 epochs, short max sequence length, gradient checkpointing. Log train/val loss, keep the best checkpoint. Then re-run: general-regression check, tool-call check, TTS-safety, and the **taxonomy per-mode metrics versus Arm B** — the claim is a measured per-mode delta, not a leaderboard score. Arm C1 joins the harness.

**Customization layer** (the per-client pipeline, a CLI, not a self-serve engine):
- Define the **client onboarding package** in `docs/ONBOARDING.md`: `business_info.md` (services, prices, hours, policies, FAQs, brand tone, hand-off rules), optional `seed_examples.jsonl`, optional `roleplay/`, optional `raw_calls/`. Levels: **L0** sheet only · **L1** + 15–30 owner-style seed examples (the realistic cold start) · **L2** + 20–40 role-play conversations · **L3** + real past conversations (only if a real partner exists).
- `build_client.py <client_dir>`: anonymise → expand/generate → format (`build_sft.py`) → train client LoRA on top of the core → evaluate → write an adapter + metrics report. Generic, no per-client code. Business-info → dialogue generation teaches facts (there is no RAG), plus negative examples: politely hand off rather than invent an unknown fact.
- Demo clients: two (e.g. clinic, restaurant) via `gen_client.py` unless a real partner exists. **The user hand-writes the L1 seed examples** (15–30 per client, in their own Urdish) so some genuine human voice enters the data; tag generated seeds `synthetic` if the user cannot.
- **Onboarding-level sweep:** train + evaluate at L0, L1 (e.g. 10/25 seeds), L2, L3 if available. Question (RQ4): with how few seeds does the adapter beat Arm B on style, facts, task completion and latency? Record wall-clock minutes and VRAM per client — "retrain cheaply when business info changes" is a product claim that needs the number.
- Real-client onboarding (questionnaire, staff role-play, WhatsApp export, post-launch flywheel) is **documented as proposed commercial onboarding, not validated**.

**Accept:** core v1 shows a measured per-mode improvement over B (or an honest null with analysis); two client adapters built by the same command; sweep curve produced.

## Phase 6 — Whisper fine-tune on Pakistani speech (STT track)

(Cover this only to the extent the user wants it in this repo; it is a proposal deliverable.) Fine-tune Whisper small/medium on consented Pakistani speech — the target script matches the Phase 1 script decision (Roman Urdish transcripts if the eval set is Roman). Report WER (and digit/phone-number-weighted WER via `jiwer`) as a **delta against the base model on the held-out set**, per taxonomy mode. Keep GPU use sequential with LLM training (one 12 GB card). If consented speech is not yet available, build the pipeline and tests now and run when data arrives; do not train on the eval set.

**Accept:** reproducible fine-tune script; WER delta table when data exists; honest note when it does not.

## Phase 7 — Latency optimisation (the differentiator)

One lever at a time: change one thing, re-run `bench_latency.py`, record TTFT/TTFS/decode/VRAM delta and any quality delta.

1. **Quantization:** FP16 vs AWQ/GPTQ int4 vs FP8 (verify Blackwell support in the engine) vs GGUF; judge quality drop, not just speed.
2. **Prefix caching:** on; keep the system prompt byte-identical across turns and short; confirm hit rate.
3. **Server tuning:** small `max_model_len`, limited `max_num_seqs`, CUDA graphs, chunked prefill, warm-up request at startup, warm adapters.
4. **Adapter strategy:** merged per-client weights (fastest) vs multi-LoRA hot-swap (flexible); measure both; ADR picks per deployment mode.
5. **Speculative decoding:** n-gram/prompt-lookup and a small draft model; keep only on net TTFS/decode gain at our reply lengths.
6. **Reply shaping:** confirm the trained short-opener lowers TTFS; tune max tokens.
7. **Streaming boundary:** verify the first clause reaches TTS as soon as it appears (livekit-agents LLM→TTS stream); measure clause-to-first-audio, including `translit.py` if used.
8. **Tokenizer-level work** only if Phase 1 shows high fertility — vocabulary surgery is risky and likely out of FYP scope; ask the user before starting, otherwise document as future work.

**Accept:** a lever-by-lever before/after table; final configuration meets or honestly misses §1.1 targets with reasons; p95 at 1/2/4 concurrency recorded.

## Phase 8 — Full evaluation and report

- Run all arms on the frozen sets: task completion, per-mode error rates, fact accuracy, style, tool-call, TTS-safety, general regression, latency, cost per minute, MOS (with human-reference ceiling) — each with CIs and significance tests.
- Charts via the `dataviz` skill into `report/`; `report/SUMMARY.md` like `urdu-tts/report/SUMMARY.md`; candid limitations (synthetic-heavy data, single judge family, one GPU, two demo clients, closed-platform ToS and version drift).
- The one-line claim to test: *"an evaluated pipeline that turns a small business onboarding package into a personalised Urdish voice-agent LLM, with measured error reduction on named failure modes of closed platforms and lower, steadier LLM latency."* Report nulls and partial wins honestly.
- Verify novelty claims with a related-work sweep (`deep-research`) before anything is asserted as "first".

## Phase 9 — Documentation, proposal deviations, optional BOL integration

- `urdu-llm/README.md` (replayable), `docs/ONBOARDING.md`, `report/DEVIATIONS.md` (model bake-off result, script track, no-RAG facts, 12 GB compute, anything else), updates to `bol/docs/architecture.md` ("LLM fine-tuning: No" → status) and `bol/docs/LATENCY.md` with measured local-LLM numbers, and the "Commercial onboarding (proposed, not validated)" section.
- **Optional / FYP-II (outside the proposal's FYP-I scope — only if the user asks):** `LLM_PROVIDER=groq|local` in `bol/backend/worker/pipeline.py` using the livekit-agents OpenAI-compatible LLM plugin pointed at the local server (verify the installed API), per-agent adapter selection without breaking existing agents (extend the `test_pipeline.py` lock test), TTFT/TTFS in `call_events` `payload.timings`, an LLM server behind the `gpu` docker-compose profile, and a live-call check via the `run` skill.

## Execution notes

- Commit at the end of each phase with a message naming the phase; run `code-review`/`simplify` first.
- Never train on `data/eval/`. Never commit real customer data or unconsented voice data; demo data is labelled synthetic.
- Ask the user before: launching very large in-session generation/judging runs (state batch count and rough usage first), vocabulary/tokenizer changes, dropping the proposal's named arms, or anything touching consent.
- Keep GPU sessions resumable (checkpoints), as in `urdu-tts`; training, Whisper fine-tuning and serving share one 12 GB card, so stop the server before training.
- A number worse than target is reported plainly; an honest negative is a valid FYP result.
