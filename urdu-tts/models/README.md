# Trained Urdu voices

Two Piper (VITS, "medium", 22.05 kHz) voices fine-tuned for BOL. Each is an `.onnx` model plus its `.onnx.json` config; the `.onnx` files are stored with Git LFS (`git lfs pull` fetches them).

| File | Voice | Trained on | Epochs | SHA-256 of the `.onnx` |
|---|---|---|---|---|
| `ur_PK-bol_rasa_male-medium.onnx` | male | ai4bharat/Rasa Urdu male, 10.0 h (conversational, emotion, assistant-command styles) | 120 | `a01c8b39520d9d1b18870325005dd17405b15866e2d49b5c2be5e8654ea785d7` |
| `ur_PK-bol_rasa_female-medium.onnx` | female | ai4bharat/Rasa Urdu female, 9.5 h (same styles) | 120 | `60abdb722cefcafab0b23d6c91f3f7196410807f3ff201edde38eda13e4b6a32` |

Results and method: [../report/SUMMARY.md](../report/SUMMARY.md). Listening samples: `../report/audio/`.

## Use

BOL serves them through `urdu-tts/server/serve.py` (see the README section "Use the voices in BOL"); copy these four files into `urdu-tts/export/` or run `python server/serve.py --voices models`. With `pip install piper-tts` they also run standalone, after the text has been through `scripts/normalize_ur.py` and the lexicons in `lexicon/` (English words are spelled in Urdu script, as the training data was).

## Licence and attribution

- **Training data:** [ai4bharat/Rasa](https://huggingface.co/datasets/ai4bharat/Rasa), CC BY 4.0. Credit: Varadhan, Sankar, Raju, Khapra, *Rasa: Building Expressive Speech Synthesis Systems for Indian Languages in Low-resource Settings*, Interspeech 2024.
- **Starting point:** the stock Piper Urdu voice `ur_PK-fasih-medium` and its checkpoint (rhasspy/piper-voices, rhasspy/piper-checkpoints). Its training data has **no stated licence**, so check this before any commercial use. These voices were made for a non-commercial final-year project.
- **Piper** (code and the model format) is GPL-3.0. BOL calls it over HTTP and does not include its code.
- **These are synthetic voices modelled on two real speakers.** Do not use them to impersonate anyone, and tell listeners the speech is synthetic.
