# Data log

Recordings and ratings are personal data. They live in the project's private database and in `data/` (git-ignored). Never commit them.

| Item | Source | Consent | Use |
|---|---|---|---|
| Speaker `c96c5c98`, 50 clips (female, 18-24, Lahore) | Recorder web app, 2026-11 | Ticked in-app consent. Confirmed by the project owner on 2026-11-25 that she is a project collaborator and agreed to her recordings being played to listening-test raters. | ASR benchmark input; human reference in the TTS listening test |
| Listening-test raters | `/listen` page | In-app consent; no name, phone or email stored | MOS, A/B preference and accent ratings |

Known issue: clips n01, n02, n04, n05, n06 of `c96c5c98` were recorded before the recorder's right-to-left digit-display fix and are excluded from scoring (flag `invalid_stimulus`).
