# Data and model sources

Every model and dataset used, with licence and consent status. `verified` says what was actually checked, not assumed.
Source tags: `real_partner` / `real_public` / `synthetic` / `real_testcall`.

## Base-model candidates (Phase 1 bake-off)

| Model | HF id | Licence (card) | Commercial use | Verified |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct | `Qwen/Qwen2.5-7B-Instruct` | Apache-2.0 | yes | HF API: `license: apache-2.0`, not gated (2026-11-11). Full LICENSE text not yet read. |
| Qwen3-8B | `Qwen/Qwen3-8B` | Apache-2.0 | yes | HF API: `license: apache-2.0`, not gated (2026-11-11). Full LICENSE text not yet read. |
| Qalb-1.0-8B-Instruct | `enstazao/Qalb-1.0-8B-Instruct` | card says Apache-2.0, **but it is a fine-tune of `unsloth/Meta-Llama-3.1-8B`** | conditional | Card read 2026-11-11. A Llama 3.1 derivative stays subject to the **Llama 3.1 Community Licence** whatever the card label says: "Built with Llama" attribution, derivative model names must start with "Llama", Acceptable Use Policy, 700M-MAU clause. Commercially usable for BOL's scale, but the conditions bind every adapter/merge we ship. **Licence text still to be read in full before this model could be chosen.** |

Note: the plan says Qalb was continued-pretrained on ~1.84B Urdu tokens; the model card says 1.97B. Immaterial to the decision; the card figure is quoted here.

### Quantised files used for the bake-off (same Q4_K_M form for all three)

Downloads over this connection run at ~2 MB/s, so the bake-off compares one common 4-bit form instead of three full bf16 downloads (user decision, 2026-11-11).

| File | Source | Made by |
|---|---|---|
| `qwen2.5-7b-instruct-q4_k_m-0000{1,2}-of-00002.gguf` | `Qwen/Qwen2.5-7B-Instruct-GGUF` | Qwen (official) |
| `Qwen3-8B-Q4_K_M.gguf` | `Qwen/Qwen3-8B-GGUF` | Qwen (official) |
| `Qalb-1.0-8B-Instruct.Q4_K_M.gguf` | `mradermacher/Qalb-1.0-8B-Instruct-GGUF` | **third party** (not the Qalb authors); quant pipeline differs from Qwen's, which is a possible confound in quality comparisons |

## Tooling

| Item | Source | Notes |
|---|---|---|
| llama.cpp `b12283`, prebuilt `ubuntu-cuda-12.8-x64` | `ggml-org/llama.cpp` release page | Official binary; used because nvcc/sudo are unavailable. MIT. |
| vLLM, torch 2.14.0+cu130 | PyPI | Versions pinned in `versions-serve.txt` |

## Bake-off test material

| File | Tag | Origin | Status |
|---|---|---|---|
| `data/bakeoff/roman_urdu_100.txt` | `synthetic` | Written by Claude in-session as phone-style sentences (orders, digits, landmark addresses, bookings, negotiation, honorifics, complaints, call handling) | User reviewed the Urdu-script file and said it looks fine (2026-11-11). Roman file and probe turns not yet individually confirmed. |
| `data/bakeoff/urdu_script_100.txt` | `synthetic` | Line-aligned Urdu-script version of the above | As above |
| `data/bakeoff/probe_30.jsonl`, `probe_systems.json` | `synthetic` | 30 Urdish caller turns, 2 invented demo businesses (Lahori Tikka House, Shifa Family Clinic) | Invented; contain no real customer data |

These are **bake-off material, not the frozen eval set**. `data/eval/` is created in Phase 3 and is never trained on.

## Not yet assessed (Phase 2)

Nexdata Urdu telephone speech sample, `mwz/UrduAssistant`, Alif Urdu-Instruct, Urdu Alpaca Filtered, Dolly Urdu, Roman-Urdu sentiment corpora: **none opened or licence-checked.** No real partner business confirmed.
