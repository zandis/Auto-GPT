# Consent explainer

`CONSENT <study> [lang=en,ja,zh-TW]` with the IRB-approved informed-consent form (ICF) attached drafts a
plain-language guide to the form: the key facts by section (purpose, what happens, duration, risks, benefits, other
choices, what the participant must do, voluntary participation and withdrawal, privacy, costs, contacts) and three to
five teach-back questions, in every requested language. The coordinator spends the consent visit on the patient's
questions instead of reading the form aloud.

## What it is not

The guide is a reading aid. It is **not the consent form, not a signature and not part of the consent record**.
TrialBox stays outside the regulated consent path: consent is still taken on the official form in the site's own
process (paper or the site's eConsent system). Every patient page says so in its own language, and says that the
consent form wins if the two differ. Releasing a guide records that a reviewer compared it with the form; it is not an
electronic signature (no 21 CFR Part 11 manifestation, no re-authentication).

## Three checks

| Check | Who | What happens to a failure |
| --- | --- | --- |
| Quote check | program | Every statement carries a word-for-word ICF quote. A quote not found in the ICF, or a number the quote does not contain, removes the statement (it cannot be kept). Translations must keep every number. |
| Second model | verifier build (Gemma 4 next to the gpt-oss-120b drafter on the Spark) | Each statement in each language is checked against its quote and back-translated into English; anything not `supported` is held back. Without a verifier the statements are marked "not verified" and the sheet says so. |
| Release | coordinator or PI (`permissions.RELEASE`, default `reviewers`) | `RELEASE <job id>` (or **Release** in the console). `drop=I03,Q2` leaves items out; `keep=I07` includes a held item. |

## Outputs

| File | When | Who gets it |
| --- | --- | --- |
| `consent_<study>_review.html` | draft | requester: every statement per language next to its quote, check results, back-translations |
| `consent_<study>_<lang>_DRAFT.html` | draft | requester: the patient page as it would be released, marked DRAFT |
| `consent_<study>.json` | draft | kept on the box: the explainer record the release reads |
| `consent_<study>_<lang>.html` | release | releaser and requester: the patient page, with who released it and when |

The ICF is study material (D1), never patient data, so all outputs are `aggregate`. The pages are plain HTML with no
script and no external request; they print on A4.

## Models

The drafter is the box's model (`TB_GATEWAY_MODEL` / `LLM_MODEL`). The second model is
`TB_GATEWAY_VERIFIER_MODEL` through the gateway (`v-verifier` on the Spark; `trialbox-stub` in the stub POC) or
`LLM_VERIFIER_BASE_URL` + `LLM_VERIFIER_MODEL` directly. Prompts: `services/orchestrator/prompts/consent_*_v1.md`.

`tools/consent_live.py` runs the same pipeline on a synthetic or public consent form against OpenRouter (development
only, D0). On the synthetic GZQO form, gpt-oss-120b + Gemma 4 took 6 calls and about US$0.02.

## Not in this version

- Interactive Q&A grounded in the ICF (spec v4 "Consent Q&A"); this version is the static guide and quiz.
- Editing a statement in the console; today the reviewer drops it, keeps it, or re-runs with a corrected form.
- Certified human translation review (the IRB's three-check process); the back-translation in the sheet supports it.
