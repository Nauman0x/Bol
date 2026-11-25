# BOL Evaluation Plan: external benchmarks and native-speaker evaluation

Written after the supervisor meeting. The supervisor's objection: comparing a model before and after training on the same (or different) sentences is self-referential. It proves the model changed, not that it is good. This plan fixes that by measuring every component against **things we did not train on and did not control**: public benchmarks, human reference recordings, and blind native-speaker judgments.

Status of claims: items marked **(verified)** were found in published sources during research; items marked **(proposed)** are our design choices and still need a pilot or the supervisor's sign-off. Nothing here has been run yet.

## 0. Principles

1. **Held-out, and speaker-disjoint.** Eval sentences, scenarios and speakers never appear in training. For speech, split by speaker, not by random clip, or the model is tested on voices it has already heard.
2. **Human ceiling and baseline floor in the same test.** Every listening test includes real human recordings of the test sentences and the stock/base system, so scores are read relative to those. MOS values cannot be compared across papers or separate tests because of contextual bias, so we only compare systems that were rated in the same session (verified: Cooper et al., [Good practices for evaluation of synthesized speech](https://arxiv.org/html/2503.03250v2)).
3. **Blind and randomised.** Raters do not know which system produced a clip. Order is shuffled and position-swapped.
4. **Native raters, screened.** Native Urdu speakers, with attention checks and listener screening (verified as recommended in the same guideline).
5. **Cite the protocol.** Naturalness tests follow the Blizzard Challenge style; quality tests follow ITU-T P.800 / P.808; the guideline asks authors to say which they followed (verified).
6. **Statistics for every comparison.** Confidence intervals and a paired test; report effect sizes and say plainly when a difference is not significant.
7. **Public benchmarks alongside our own set.** A result on our private set alone cannot be checked by anyone else.

## 1. TTS (Piper Urdu voice)

### 1.1 Test material
- 100+ sentences, none in training. Three buckets: (a) held-out Rasa test sentences (casual conversational), (b) phone-business sentences written for BOL (greetings, order confirmation, prices), (c) hard cases: phone numbers, digits, English loanwords/code-switching, honorifics.
- **Human reference recordings of the same sentences.** For bucket (a) the original Rasa recordings are the natural reference. For (b) and (c), a native speaker on the team records them (quiet room, same mic, 44.1/48 kHz mono WAV).

### 1.2 Systems in the test
| ID | System | Purpose |
|---|---|---|
| H | Human recording | ceiling (hidden reference) |
| S | Stock `ur_PK-fasih-medium` | baseline we started from |
| F | Our fine-tuned voice | system under test |
| X | Optional: one other open/commercial Urdu TTS | external yardstick (must check licence/availability first) |
| L | Optional low anchor (e.g. degraded audio) | catches careless raters |

### 1.3 Subjective tests (native listeners)
- **MOS naturalness, ACR 1-5**, all systems mixed per listener, following P.800 / [P.808 crowdsourcing](https://arxiv.org/pdf/2005.08138). Precedent: the URDUTTS dataset paper used MOS from 40 native speakers (verified: [LREC 2026](https://aclanthology.org/2026.lrec-1.859/)). **Target: 30+ listeners (proposed).** Report mean with 95% CI per system.
- **Pairwise preference (AB, and CMOS -3..+3)** for F vs S and F vs H. MOS often cannot separate similar systems; pairwise is more sensitive but slower (verified: [Rethinking MUSHRA](https://arxiv.org/abs/2411.12719)).
- **MUSHRA is not used as the primary test.** Cooper et al. note there is no standardised reference for TTS, and the Rethinking MUSHRA paper argues its human-reference anchoring can penalise modern TTS. If the supervisor wants it, run a small MUSHRA-style session with 5-6 stimuli per screen to limit fatigue (verified: [MUSHRA-1S](https://arxiv.org/html/2509.19219v1)).
- **Intelligibility:** listeners type what they hear for a subset including numbers and code-switched sentences; score WER/CER against the intended text. This matters more for phone agents than naturalness.
- **Appropriateness for a business call (proposed):** 1-5 rating "would you be comfortable hearing this on a business phone call".

### 1.4 Objective metrics (supplementary, never the headline)
- CER/WER of an ASR model on the synthesised audio (already in `scripts/eval_cer.py`, Whisper large-v3). State the ASR model and text normalisation; ASR error is a proxy because the ASR itself is imperfect on Urdu.
- Duration/rate and F0 statistics vs the human reference (proposed).
- Real-time factor and time to first audio on CPU.
- A predicted-MOS model (e.g. UTMOS) can be added as a sanity check, not a result. **Unverified for Urdu**; do not rely on it.

### 1.5 Analysis
- Paired comparison per sentence/listener: Wilcoxon signed-rank or a mixed-effects model with listener and sentence as random effects; bootstrap CIs; correct for multiple comparisons. State the test used (the guideline asks for this).
- Report per bucket (a/b/c), since a voice can win on casual speech and lose on digits.

## 2. ASR (Whisper fine-tune on Pakistani speech)

This is where native-speaker recordings are the **test input**.

### 2.1 Test sets
1. **Public:** Common Voice Urdu test and FLEURS Urdu. Published Urdu benchmarks exist for Whisper, MMS and SeamlessM4T on these (verified: [WER We Stand](https://arxiv.org/pdf/2409.11252), [Interspeech 2026 South Asian ASR failures](https://aghaaliraza.com/publications/2026--Interspeech--Dissecting_ASR_Failures_in_Low-Resource_South_Asian_Languages.pdf)). Reproduce a published baseline first to prove our WER pipeline is sound.
2. **Our own consented Pakistani-speech eval set** (the 50-100 speaker set in the proposal): never trained on, speaker-disjoint from the fine-tuning data.

### 2.2 Recording protocol (proposed)
- Written consent before recording (voice is biometric). Log in `data/SOURCES.md`.
- Spread across gender, age band, and region/accent; record speaker metadata.
- Two conditions: clean microphone and a real phone-call channel (8 kHz telephone), because deployment is telephony.
- Script mix: read sentences, digit strings and phone numbers, business phrases, code-switched Urdu-English, plus some unscripted answers (read speech flatters ASR; the benchmark paper found different winners on read vs conversational data, verified).
- Two independent native transcribers per utterance, disagreements resolved; report transcriber agreement.

### 2.3 Metrics and fairness
- WER and CER, plus a digit/phone-number-weighted WER (already in plan).
- **Fixed text normalisation, written down and applied identically to every system.** The literature warns that WER on Urdu is unreliable without it, and that output in the wrong script inflates WER (verified in both papers above).
- Systems: Whisper base, our fine-tune, and at least one other open model (e.g. SeamlessM4T or MMS) as external yardstick.
- Slice by speaker, gender, channel, and sentence type. Bootstrap CIs resampling **speakers**, not utterances.

## 3. LLM (Urdish dialogue model)

### 3.1 Native-speaker evaluation
- Fixed set of 100-150 held-out scenarios (orders, bookings, negotiation, honorifics, code-switching).
- Outputs from arms A/B/C (per the main plan) shown **blind, shuffled, position-swapped** to native Urdu/Urdish speakers.
- Two tasks: pairwise preference and a rubric score (naturalness, correct honorific/register, code-switch handling, task correctness). This mirrors Urdu/Indic evaluations that use native-speaker ranking and pairwise comparison (verified: [Generalists vs. Specialists](https://arxiv.org/pdf/2407.04459v3), [Indic pairwise study](https://arxiv.org/pdf/2406.15053v1)).
- **At least 3 raters per item (proposed; UrBLiMP used at least 3 native annotators per item, verified: [UrBLiMP](https://arxiv.org/pdf/2508.01006)).** Report inter-annotator agreement (Fleiss' kappa or Krippendorff's alpha). Low agreement is a finding about the rubric, not something to hide.

### 3.2 About the in-session Claude judge
The current plan uses Claude Code as judge. The supervisor's point applies here too: an LLM judge is not a native speaker. **Treat it only as a cheap scaler**, and validate it: have native raters label a sample (e.g. 100 items), report judge-vs-human agreement, and make headline claims from the human-rated results. Prior Urdu work compared LLM judges to native annotators with Krippendorff's alpha for exactly this reason (verified: Generalists vs. Specialists).

### 3.3 Automatic and public checks
- Task completion on scripted scenarios, tool-call accuracy, TTS-safety, fact accuracy (as in main plan).
- Regression on a public Urdu benchmark before/after fine-tuning (forgetting check). Candidate: Urdu linguistic-competence minimal pairs ([UrBLiMP](https://arxiv.org/pdf/2508.01006)); confirm dataset availability and licence first.

## 4. End-to-end (the actual product claim)
Run full calls (speech in, agent, speech out) on the same scripted scenarios for: closed platform baseline, open stack prompt-only, our stack. Native listeners rate whole-call quality, and we log task success, latency and cost per minute. This is what the "better than closed platforms for Pakistani callers" claim rests on.

## 5. Sample sizes and pilots (proposed, to be justified)
Do not guess; run a pilot of ~10 listeners / ~20 sentences, estimate rating variance, then size the main test so the CI is narrow enough to separate F from S. Report the final counts (listeners, sentences, ratings per sample), since reviewers are asked to check these (verified).

## 6. Threats to validity (write these in the report)
- Single speaker and male-only training voice for TTS.
- Synthetic-heavy LLM data; judge from the same model family as the data generator.
- Raters recruited from our own network may skew young/urban; record demographics.
- Test-set leakage: keep `data/eval/` frozen and hash it; check no eval sentence is in any training file.
- Closed-platform versions drift and ToS may restrict benchmarking.

## 7. Deliverables checklist
- [ ] Frozen eval sentences + scenarios, hashed, leakage check script
- [ ] Human reference recordings (TTS) and consented speech eval set (ASR)
- [ ] Listening-test web form (randomised, hidden reference, anchor, attention checks)
- [ ] Rater recruitment plan with demographics and consent
- [ ] Scoring scripts: WER/CER with fixed normalisation, MOS/CMOS stats, kappa/alpha
- [ ] Reproduced published baseline on Common Voice / FLEURS Urdu
- [ ] Results tables with CIs, per-slice breakdown, limitations

## Open items I could not verify
- No Urdu-specific CMOS/MUSHRA protocol (listener counts, anchors) was found; numbers above are design choices to justify with a pilot.
- Seed-TTS-eval and similar speaker-similarity benchmarks were not confirmed, and are not needed for a single-speaker voice.
- The exact statistical recommendations in Cooper et al. section 4 were not retrieved; read the paper before fixing the test choice.
