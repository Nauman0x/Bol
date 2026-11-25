# Data log

Recordings and ratings are personal data. They live in the project's private database and in `data/` (git-ignored). Never commit them.

| Item | Source | Consent | Use |
|---|---|---|---|
| Speaker `c96c5c98`, 50 clips (female, 18-24, Lahore) | Recorder web app, 2026-11 | Ticked in-app consent. Project owner stated on 2026-11-25 that she is a project collaborator who agreed to her recordings being played to listening-test raters. | ASR benchmark input; human reference in the TTS listening test |
| Esha (female), ~1,690 recorded sentences + 80 held-out test recordings | Project recording tool (`urdu-tts/recording`), 2026-11-11 | Project owner stated on 2026-11-25 that Esha is the same person as `c96c5c98` and has agreed to her recordings being played to raters | Training data for the Esha TTS voice; her 80 held-out real recordings are the human ceiling in listening test v2 |
| Listening-test raters | `/listen` page | In-app consent; no name, phone or email stored | MOS, A/B preference and accent ratings |

Known issue: clips n01, n02, n04, n05, n06 of `c96c5c98` were recorded before the recorder's right-to-left digit-display fix and are excluded from scoring (flag `invalid_stimulus`).

The Esha identity statement and consent above are the project owner's statements, not independently verified. Keep her recordings private: they live in the Aiven database and in git-ignored `data/` folders only.
