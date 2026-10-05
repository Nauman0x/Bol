# Final Year Project Proposal

## Business-Adaptive Voice AI: Conversation-Driven LLM Personalization and Style-Aware Speech Synthesis for AI Phone Agents

**Based on an existing open-source AI phone-calling project**

---

## Abstract

The base project is a working, open-source AI phone-calling platform: a caller rings a real number, an LLM-backed agent transcribes, reasons, and replies over a live SIP/WebRTC call, with retrieval-based knowledge lookup, function-calling tools, and a bilingual (English/Arabic) speech stack. Its core limitation is that every business's agent is the *same* shared foundation model, differentiated only by a hand-written system-prompt string, and speaks with a hand-picked stock voice with no control over delivery. This proposal extends it into a **business-adaptive voice AI platform**: businesses fine-tune a lightweight adapter on their own historical call transcripts so the agent learns their terminology, policies, and communication style, combined with the platform's existing retrieval system for facts that change too often to bake into weights; and businesses receive a **Voice Style Profile** that lets their agent's *delivery* — pace, pauses, emphasis, tone — stay consistent with their brand rather than being an accident of whichever stock voice was picked. The project's contribution is not any single technique (LoRA, RAG, and neural TTS are all established) but the **evaluated combination and its data pipeline**: turning raw call logs into training data and a style profile, and measuring, honestly, when fine-tuning is worth it against RAG alone.

---

## 1. The Current Project

The base project (`README.md`, `docs/PLAN.md`) is a multi-tenant SaaS-style platform, self-hostable end-to-end except for the PSTN carrier connection. An organization creates an "agent" (system prompt, voice, tools, knowledge access), attaches a phone number, and the agent holds live conversations with callers. It is implemented, not a prototype: FastAPI + PostgreSQL backend, a stateless `livekit-agents` Python worker running the voice pipeline, and a Next.js dashboard.

**What already works** (verified against source; see `docs/architecture.md` for details):

- Real inbound/outbound PSTN calls via LiveKit + Telnyx SIP, plus free browser test calls.
- STT (Groq-hosted Whisper, or LiveKit's streaming gateway), LLM (Groq-hosted Qwen3, model/temperature configurable per agent), TTS (Groq Orpheus, Fish Audio streaming, or self-hosted Chatterbox).
- Function-calling tools: end call, transfer call, send DTMF, and a generic outbound-webhook tool for CRM/booking integrations.
- A working retrieval pipeline: uploaded documents are chunked, embedded (multilingual `fastembed` model), and searched by cosine similarity when the LLM decides to call a `lookup_knowledge` tool mid-conversation.
- Full call transcripts (`call_events`), recordings, post-call LLM analysis against a customer-defined schema, and cost/latency analytics per call.
- Native bilingual (English/Arabic) design, including RTL-aware UI and Arabic-specific STT/TTS models.

## 2. Current Architecture (summary)

```
PSTN caller ──▶ Telnyx SIP ──▶ LiveKit (SFU + SIP bridge) ◀── Browser test call
                                        │  agent joins as participant
                                        ▼
                         Worker (livekit-agents, stateless)
                    VAD → STT → LLM (Groq/Qwen3) → TTS, tool calls
                                        │  HTTP only (no DB access)
                                        ▼
                      FastAPI API  ──▶  PostgreSQL (agents, calls,
                      (/internal/*)     call_events, knowledge_chunks, ...)
                                        Redis (cache)
```

The worker holds no database connection — it fetches agent config and reports events over HTTP, which is what lets it scale horizontally. Knowledge retrieval is a plain cosine-similarity search over embedded document chunks, invoked as an LLM tool call, not injected into the prompt at session start. Full detail in `docs/architecture.md`.

## 3. Problems and Limitations in the Current System

| # | Limitation | Why it matters |
|---|---|---|
| 1 | **No LLM personalization.** Every org uses the identical shared Groq model. The only per-business signal is a manually written prompt string. | The agent cannot learn a business's actual phrasing, policies, or common-intent handling from the conversations it has already had — that data is stored (`call_events`) and never used. |
| 2 | **No TTS delivery control.** TTS calls carry text and a fixed `voice_id` only — no prosody, pacing, pause, or emotion parameter exists anywhere in the pipeline. | Every business sounds like a stock voice reading text; there is no way to express brand personality or match delivery to context (apology vs. sales vs. confirmation). |
| 3 | **Knowledge base is basic and organization-wide.** Fixed-size character chunking, brute-force cosine search, no per-agent scoping, no vector index. | Adequate for a handful of documents; retrieval quality and scoping are real ceilings as knowledge bases grow, and it does nothing to influence *how* the agent talks. |
| 4 | **No feedback loop from real calls to agent quality.** Transcripts and post-call analysis are captured but never used to improve the model or flag communication-style drift. | The system accumulates exactly the data a personalization approach needs, and currently wastes it. |
| 5 | **Platform reliability/observability gaps** (call-state bugs, unfinished auth lifecycle, no logging) documented in the independent engineering audit (`Kimi_audit.md`). | Out of scope for this proposal, but scoping decisions below deliberately avoid depending on these unfinished layers. |

Limitations 1–2 are the direct target of this proposal; 3 is extended, not rebuilt; 4 is the resource being unlocked; 5 is explicitly out of scope.

## 4. Proposed FYP System

**Business-Adaptive Voice AI**: businesses upload or accumulate historical call transcripts and business documents, and the platform learns two separate things from that data:

- **What the business knows and how it responds** — via a lightweight fine-tuned adapter (LoRA/QLoRA) on top of an open-weight instruction-tuned LLM, trained on that business's cleaned conversation history, combined with the existing retrieval system for fast-changing facts.
- **How the business sounds** — via a **Voice Style Profile**: a structured, per-business record of speaking rate, pause behavior, emphasis patterns, and tone-per-intent, applied automatically at synthesis time on top of a selected or cloned base voice.

The rest of the platform (telephony, call handling, dashboard, tools) is unchanged; this is an addition to the LLM and TTS stages of the existing pipeline, not a new product.

## 5. Proposed Architecture

```
                     ┌───────────────────────────────────────────┐
                     │        Existing call pipeline (base project) │
                     │   VAD → STT → [LLM stage] → [TTS stage]     │
                     └───────────────┬─────────────┬──────────────┘
                                     │             │
                        ┌────────────▼───┐   ┌─────▼─────────────┐
                        │  LLM stage:     │   │  TTS stage:        │
                        │  base model +   │   │  base voice +      │
                        │  per-org LoRA   │   │  Voice Style        │
                        │  adapter, with  │   │  Profile-driven     │
                        │  RAG tool call  │   │  delivery control   │
                        │  for facts      │   │  (rate/pause/       │
                        └────────▲────────┘   │  emphasis/emotion)  │
                                 │             └─────────▲───────────┘
             ┌───────────────────┴──────────┐            │
             │   Offline personalization pipeline (new)   │
             │                                             │
             │  call_events ──▶ clean & PII-redact ──▶     │
             │  convert to instruction-tuning pairs ──▶    │
             │  QLoRA fine-tune (per org) ──▶ adapter store │
             │                                             │
             │  reference audio / transcripts ──▶ extract  │
             │  prosodic + lexical features ──▶ Voice Style │
             │  Profile (stored per org)                    │
             └─────────────────────────────────────────────┘
```

The offline pipeline is a new batch process, run periodically (or on demand) per organization; the online call pipeline changes only in which adapter/profile it loads for a given org — the worker's existing "fetch config, build pipeline" pattern extends naturally to "fetch config + adapter reference + style profile."

## 6. LLM Fine-Tuning / Personalization Approach

### 6.1 Training data: from raw transcripts to training pairs

1. **Source**: `call_events` rows (`transcript_user`, `transcript_agent`), grouped by `call_id`, ordered by timestamp — this data already exists per organization.
2. **Filtering**: drop failed/very short calls, drop calls flagged low-quality by the existing post-call analysis, deduplicate boilerplate greetings/closings so the model doesn't overfit to them.
3. **PII redaction**: regex/NER pass over phone numbers, names, addresses, and payment-related utterances before any data leaves the raw-transcript store — a hard requirement given this is customer conversation data.
4. **Conversion**: each turn becomes an instruction-tuning example — `{system_prompt (business persona), conversation history so far, target agent reply}` in a standard chat-template JSONL format — plus lightweight metadata (an intent label from clustering or the existing post-call analysis schema) usable for stratified sampling and evaluation slicing.
5. **Style feature extraction**: alongside training pairs, compute per-business lexical statistics (average reply length, formality markers, characteristic phrases, greeting/closing patterns) — this doubles as an input to the fine-tuning conditioning and as the seed for the Voice Style Profile (§7), tying the "what" and "how" pipelines to the same source data.

### 6.2 Data volume — an honest constraint

A single SMB's real call history is very unlikely to provide the thousands of clean turns a fine-tune ideally wants. This proposal treats that as a scoping fact, not something to paper over: the FYP evaluates on (a) a small real/pilot dataset from test agents built during the project, and (b) a validated synthetic-augmentation set (LLM-generated paraphrases and style-consistent synthetic conversations, filtered to match the extracted style statistics) — explicitly reported as a limitation on real-world generalizability, with a discussion of what data volume a production deployment would actually need.

### 6.3 Model and training method

- **Base model**: a small, open, instruction-tuned model realistic for single-GPU/Colab-class compute — e.g., **Qwen2.5-7B-Instruct** or **Llama-3.1-8B-Instruct** — deliberately *not* the 32B production model the base platform uses live, since full fine-tuning or even QLoRA on a 32B model is outside FYP-scale compute and time.
- **Method**: **QLoRA** (4-bit NF4 quantized base weights + LoRA adapters on attention/MLP projections, via PEFT + bitsandbytes + a standard SFT trainer). Rank and target modules swept as part of the experiment, not fixed up front.
- **Per-organization adapters**: one small adapter per business (typically tens of MB), loaded at inference time on top of a shared quantized base — this is what keeps the approach realistic to serve multiple businesses without hosting a full model copy each.
- **Serving path for the prototype**: adapters are loaded locally for evaluation; a note on production serving (e.g., dynamic LoRA swapping via vLLM/SGLang multi-LoRA serving) is included in the roadmap as a discussion point, not built, since the base platform's live LLM stage is a hosted Groq endpoint that does not currently support custom weights — the prototype runs its own local inference server for the fine-tuned condition.

### 6.4 RAG vs. Fine-Tuning vs. Hybrid

| Dimension | RAG only (current system) | Fine-tuning only | Hybrid (proposed) |
|---|---|---|---|
| Fact freshness | High — retrieves current documents | Low — facts frozen at training time, stale as business info changes | High — facts still retrieved live |
| Hallucination on business facts | Low, if retrieval fires and is relevant | Higher — model can confidently state outdated or invented facts | Low — same retrieval safety net |
| Communication style / tone control | Weak — a small model under real conversational pressure follows style instructions in a prompt inconsistently | Strong — style is learned into weights, applied even when not explicitly reminded | Strong — inherited from fine-tuning |
| Handling of recurring intents/policies not explicitly documented | Weak — only surfaces what's literally in uploaded documents | Strong — learns implicit patterns from example conversations | Strong |
| Data/maintenance cost | Low — re-index on document change | Higher — retraining needed as style/policy evolves | Medium — retrain less often (style/policy), re-index cheaply (facts) |
| Latency/cost overhead vs. base | Small (one retrieval call) | None at inference (adapter is fused/loaded once) | Small (retrieval only when needed) |
| Realistic with an SMB's actual data volume | Yes — works with a handful of documents | Marginal — needs enough conversation volume/augmentation | Yes — fine-tuning workload is smaller (style, not facts) |

**Recommendation: hybrid, not fine-tuning-first.** The technical justification is precise, not aspirational: fine-tuning is well-suited to *behavior that is stable and recurring* — how the business phrases things, which tools it reaches for, how it handles common intents — because that pattern repeats across many training examples and generalizes. It is poorly suited to *facts that change* (prices, hours, promotions, inventory), because a model has no mechanism to "forget" a stale fact it was trained on, and retraining on every business-data change is not viable. RAG has exactly the opposite profile. The hybrid design keeps the base platform's existing retrieval system responsible for facts and adds fine-tuning responsible for style, tool-use conventions, and intent handling — each technique used for what it is actually good at. This project does **not** assume fine-tuning is superior; §9 defines the experiment that tests this claim rather than asserting it.

### 6.5 Evaluation of the LLM component

- **Automatic**: held-out conversation perplexity/next-turn accuracy; tool-call format/argument accuracy; adherence to length/style constraints from the guardrail preamble; a factual-QA set with known-correct answers to measure hallucination rate per condition (RAG-only / fine-tune-only / hybrid).
- **Style fidelity**: embedding-based stylistic distance between generated replies and the business's real historical replies (using the same style-feature vector computed in §6.1), plus lexical-overlap metrics on characteristic phrases.
- **Human/LLM-judge preference**: pairwise comparison (RAG-only vs. fine-tune-only vs. hybrid) on style match, factual correctness, and naturalness, using a rubric rather than free-form judgment to keep it reproducible.

## 7. TTS / Voice Personalization Approach — the Voice Style Profile

This is the area given deliberate special weight, because it is the platform's least-developed dimension today (TTS is currently "text + fixed voice_id, nothing else") and the area least explored by comparable open-source voice-agent projects.

### 7.1 What a Voice Style Profile is

A structured, per-business record capturing *how* the agent should speak, independent of *what* it says:

| Attribute | Source | Effect at synthesis time |
|---|---|---|
| Base voice | Selected stock voice, or a cloned voice from a short reference clip | Which voice model/embedding is used |
| Speaking rate | Extracted from reference audio (words/min) or manually set | Rate parameter passed to the TTS engine |
| Pause behavior | Extracted pause statistics after greetings, before key information, at sentence boundaries | Inserted pause markers in the delivery-annotated text |
| Emphasis | Business/product names, key terms marked for stress | Emphasis markup around those tokens |
| Pronunciation overrides | Business/product name pronunciations (a TTS-side analogue of the STT-side `boosted_keywords` field already in the schema) | Phoneme/lexicon override at synthesis |
| Tone-by-intent | Default tone mapped to coarse conversational intent (apology → calmer/slower, sales → warmer/upbeat, confirmation → neutral) | Selects an emotion/intensity setting per utterance, not globally fixed |

### 7.2 How it is built and applied

1. **Extraction**: from a small set of reference audio (a business's own IVR recordings, or a short scripted reading) using standard prosodic-analysis tooling (e.g., `librosa`/`Praat`-style pitch, rate, and pause extraction) to seed default profile values; a manual override UI is the fallback for businesses with no reference audio.
2. **Context-aware delivery at call time**: rather than sending the LLM's raw text straight to TTS, a lightweight **delivery controller** step tags the outgoing text with the Voice Style Profile's settings plus a coarse intent/emotion signal inferred from the conversation turn (e.g., detected from the post-call-analysis-style classification already used elsewhere in the base platform, applied per-turn instead of per-call) — producing delivery-annotated text (pause/emphasis/rate markers) before synthesis.
3. **Synthesis substrate**: implemented against the base platform's existing self-hosted Chatterbox integration (`deploy/chatterbox/`, `worker/chatterbox_tts.py`) rather than a new TTS engine — Chatterbox already supports zero-shot voice cloning and (per its underlying server's API surface) generation-control parameters beyond what the current OpenAI-compatible wrapper passes through today. Part of the project's engineering work is extending that integration to expose and drive those parameters from a Voice Style Profile, rather than inventing new TTS technology.
4. **Consistency**: once built, a business's profile is applied automatically to every call — this is what makes it "personalization" rather than a per-call setting an operator has to remember to configure.

### 7.3 Evaluation of the TTS component

- **Objective**: measured adherence of synthesized speech to the target profile (rate, pause timing) against the reference audio.
- **Subjective**: listener preference tests (AB/MUSHRA-style) comparing (a) stock default voice, (b) cloned voice with no style control, (c) cloned voice + Voice Style Profile — on perceived brand consistency, naturalness, and appropriateness of tone to conversational context.
- **Consistency check**: variance of delivered rate/tone across many calls for the same business, to confirm the profile is actually being applied consistently rather than drifting per call.

## 8. What Makes This Different from a Normal Chatbot or RAG System

A standard RAG chatbot retrieves facts and answers questions; it does not learn how an organization *characteristically* communicates, and it has no concept of vocal delivery at all beyond picking a voice. This project's difference is specific and falls out of the two pipelines above:

- The LLM stage learns from the business's *own conversation history*, not just its documents — behavioral and stylistic patterns a retrieval system structurally cannot capture, because they are not written down anywhere as "facts."
- The retrieval system is kept, not replaced — this is a hybrid architecture with a stated division of labor, not a fine-tuning pitch.
- The TTS stage is treated as a personalization surface in its own right, with a structured, reusable profile driving delivery — most voice-agent products (including the base platform today) stop at "pick a voice."
- The two pipelines share a data source (`call_events`) and a style-feature extraction step, coupling "what to say" and "how to say it" to the same underlying signal instead of treating them as unrelated features.

## 9. Research Novelty vs. Engineering — an honest accounting

To be explicit about what is, and is not, a research contribution:

**Not novel (established technology, used as-is):** LoRA/QLoRA fine-tuning, retrieval-augmented generation, neural TTS with voice cloning, function-calling LLM agents. None of these are claimed as new techniques.

**The actual contribution:**
1. A **concrete, evaluated data pipeline** that converts a voice-agent platform's own call logs into (a) fine-tuning data and (b) a communication style profile — and an honest empirical answer, on real system data, to *when personalization is worth it* rather than assuming it is.
2. A **hybrid RAG+fine-tuning architecture with a stated, tested division of labor** (facts vs. behavior) rather than treating the two as competing options, evaluated head-to-head under conditions realistic for a small business's actual data volume.
3. The **Voice Style Profile** as a structured intermediate representation between "what an LLM decided to say" and "how a TTS engine renders it" — coupling delivery to conversational context (per-turn, not per-call) and to a business-specific profile extracted from data, which goes beyond both the base platform's current TTS handling and the "voice + emotion tag" pattern common in existing TTS APIs.

The value of the project is the engineering-plus-evaluation of a coherent pipeline that does not yet exist here, and a defensible answer about which approach is actually worth the complexity — not the invention of a new model or algorithm.

## 10. Research Questions

- **RQ1**: Does fine-tuning an open-weight LLM on a business's historical call transcripts measurably improve style/tone fidelity and intent-handling consistency compared to prompt-only and RAG-only baselines, at data volumes realistic for an SMB?
- **RQ2**: Does combining fine-tuning (for style/behavior) with retrieval (for facts) reduce hallucination on business-specific facts compared to fine-tuning alone, without losing the style gains of RQ1?
- **RQ3**: Can a per-business Voice Style Profile, extracted from limited reference audio/data and applied automatically at synthesis time, produce speech that listeners perceive as more brand-consistent and contextually appropriate than a fixed stock voice, without a measurable latency regression in the existing pipeline's real-time budget?
- **RQ4**: What is the minimum conversation-data volume at which fine-tuning-based personalization starts to outperform RAG-only prompting on style fidelity — i.e., where is the practical break-even point that should govern a real deployment recommendation?

## 11. Evaluation Methodology

| Component | Method | Baselines compared | Key metrics |
|---|---|---|---|
| LLM personalization | Held-out conversation eval + human/LLM-judge pairwise preference | Prompt-only (current system), RAG-only, fine-tune-only, hybrid | Style-fidelity distance, tool-call accuracy, hallucination rate on a fact QA set, judge win-rate |
| TTS personalization | Objective acoustic analysis + subjective listening test | Stock voice, cloned voice (no style control), cloned voice + Voice Style Profile | Rate/pause adherence to target profile, MOS/AB preference, tone-appropriateness rating |
| End-to-end | Simulated call sessions through the actual base-platform pipeline (browser test-call path) | Current system vs. personalized configuration | Perceived quality, task success on scripted scenarios, latency overhead |
| Data-volume sensitivity | Ablation over training-set size (real + synthetic-augmented) | — | Style-fidelity curve vs. data volume, answering RQ4 |

All comparisons run against the same test-agent scenarios (a small number of representative business personas, e.g., a clinic receptionist and a retail support line, each in English and Arabic) to keep results comparable across conditions.

## 12. Expected Results

Framed as testable hypotheses, not guaranteed outcomes:

- The hybrid condition is expected to achieve the best combined score (style fidelity + factual accuracy), because it is architected to avoid each standalone approach's specific weakness.
- Fine-tuning-only is expected to show measurably higher hallucination on facts that were true at training time but have since changed, demonstrating why RAG remains necessary even after fine-tuning.
- RAG-only is expected to underperform on style-fidelity and tool-use-convention metrics, since retrieved text cannot change the model's own phrasing habits.
- The Voice Style Profile condition is expected to be preferred over a stock voice for brand-consistency judgments, with the size of that preference likely varying by how distinct the target business's implied "brand personality" is (a genuinely open empirical question, not assumed).
- A data-volume threshold below which fine-tuning gains disappear into noise is expected to exist and is worth reporting explicitly, since it is directly actionable for a real deployment decision.

## 13. FYP Scope and Feasibility

**In scope**, built as extensions to the existing worker/API without touching its telephony or reliability layers:
- Offline data pipeline: transcript export, cleaning, PII redaction, format conversion, style-feature extraction (batch scripts against the existing `call_events`/`knowledge` schema).
- QLoRA fine-tuning pipeline and evaluation harness on a small (7–8B) open model, run locally/on rented GPU time — not the production Groq model.
- A local inference server for the fine-tuned condition, wired into a modified copy of `worker/pipeline.py`'s LLM stage for evaluation purposes.
- Voice Style Profile extraction (from reference audio) and a delivery-controller step feeding the existing Chatterbox integration, extended to pass through generation-control parameters.
- The evaluation suite in §11, run on synthetic/pilot business personas built for the project (2–3 personas × 2 languages).

**Out of scope** (explicitly, to keep the project realistic in one/two semesters):
- Fixing the base platform's unrelated issues (auth, observability, webhook durability) documented in the engineering audit.
- Production multi-tenant adapter-serving infrastructure (e.g., dynamic LoRA swapping at scale) — discussed as future work, not built.
- Full fine-tuning or fine-tuning of the 32B production model.
- Sourcing real production call data from an actual operating business (assumed unavailable; pilot/synthetic data used instead, with the resulting limitation stated openly).

**Feasibility**: every component maps to a known, bounded technique (QLoRA, PEFT, standard prosodic feature extraction, an existing self-hosted TTS server) rather than open-ended research, and reuses the base platform's existing config/provider-abstraction seams rather than requiring new platform architecture — the risk profile is in data preparation and evaluation design, not in the underlying methods.

## 14. Implementation Roadmap

| Phase | Weeks | Deliverable |
|---|---|---|
| 1. Setup & data pipeline | 1–4 | Transcript export/cleaning/PII-redaction/format-conversion scripts against real test-agent data; style-feature extractor |
| 2. Baselines | 5–7 | Prompt-only and RAG-only evaluation harness running against the existing knowledge pipeline; fact QA eval set built |
| 3. Fine-tuning pipeline | 8–12 | QLoRA training pipeline on chosen 7–8B base model; per-persona adapters trained on pilot/synthetic data |
| 4. Hybrid integration | 13–15 | Fine-tuned model + retrieval tool call wired together; end-to-end test-call path working with a personalized agent |
| 5. Voice Style Profile | 13–17 (parallel with 4) | Prosodic feature extraction from reference audio; delivery controller; extended Chatterbox integration exposing generation-control parameters |
| 6. Evaluation | 18–21 | Full evaluation suite (§11) run across all conditions and personas; data-volume ablation for RQ4 |
| 7. Write-up | 22–24 | Results analysis, thesis/report, demo |

## 15. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Insufficient real conversation data to fine-tune meaningfully | Validated synthetic augmentation (§6.2); report the data-volume ablation (RQ4) as a first-class result, not a footnote |
| GPU compute constraints for fine-tuning | Small (7–8B) base model + QLoRA (4-bit), targeting single-GPU/cloud-credit-scale compute from the outset |
| Style/emotion evaluation is inherently subjective | Combine objective acoustic metrics with structured (rubric-based) listening tests, not free-form opinion |
| Chatterbox server's native parameter surface is less flexible than expected | Scope §7's delivery controller to whatever parameters are actually exposed; degrade gracefully to rate/voice-selection only if emotion control proves unavailable, and document the gap |
| Scope creep into fixing unrelated platform issues | §13's out-of-scope list is a hard boundary for the project |

## 16. Conclusion

The base platform already has the two things a personalization project needs most: a real, working voice pipeline with clean seams for swapping the LLM and TTS stages, and a growing store of exactly the conversational data such a project would learn from. What it does not yet have is any mechanism to turn that data into a business-specific model or voice. This proposal is scoped to build and, more importantly, **evaluate** that mechanism — a hybrid fine-tuning-plus-retrieval approach for what the agent says, and a Voice Style Profile for how it says it — with an explicit, testable claim about when each technique is worth its cost, rather than treating either as self-evidently better.

---

## References (indicative)

- Hu et al., "LoRA: Low-Rank Adaptation of Large Language Models," 2021.
- Dettmers et al., "QLoRA: Efficient Finetuning of Quantized LLMs," 2023.
- Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks," 2020.
- Resemble AI, "Chatterbox," open-source TTS model, 2025.
- Qwen Team, "Qwen2.5/Qwen3 Technical Report."
- Base project documentation: `README.md`, `docs/RESEARCH.md`, `docs/PLAN.md`, `docs/LATENCY.md`, `docs/architecture.md`, `docs/project-analysis.md`, engineering audit notes.
