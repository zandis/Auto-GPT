# D-1387 A person's own preferences: density, text size, colour mode and language, without quiet hours (10F-1)

- **Task:** plan 10 card 10F-1 (`docs/plan/47-plan-10-2026-11-18.md`, line 640; review 16 card 16-26), lane K.
  **Date:** 2026-11-20
- **What the card asks for:** "Per-user preferences: density, text size, colour mode with high contrast, language,
  quiet hours"; proof "a choice survives sign-out; contrast passes in every mode". Review 16 §5.1 (the per-user
  level) adds: "how things look and what they see first, inside what their role already shows", "density
  (comfortable / compact), text size (100–150 %), colour mode (system / light / dark / high contrast), language",
  "kept per user, audited as `pref.set`"; §8.2: a table `user_pref` (user, key, value, at), "per-user preferences
  save immediately". In a list:
  1. density, comfortable or compact;
  2. text size, 100 to 150 %;
  3. colour mode: system, light, dark, high contrast;
  4. language;
  5. quiet hours;
  6. kept per person, surviving sign-out, in a `user_pref` table;
  7. each change audited (`pref.set`);
  8. contrast passes in every mode.
- **The owner's ruling (2026-11-20 00:10 UTC):** yes to 10F-1 **without quiet hours**; limited to what the person's
  role and the study's delegation log already show; audited where it widens anything.
- **Decision (what was built):**
  - **Four keys, each a closed set** (`services/console/prefs.py`): `density` (comfortable, compact), `text_size`
    (100, 125, 150), `mode` (system, light, dark, contrast), `lang` (auto, en, ja, zh-TW). The first value is the
    default and is the console as it was. No value is free text: each is one fixed word, so none can hold a
    pseudonym, a name or any patient-linked value.
  - **The store:** `auth.user_pref` (username, name, value, at; one row per key that differs from its default), a new
    schema version of the accounts store (`SCHEMA_V9`, `CREATE TABLE IF NOT EXISTS`: nothing stored changes; checksum
    pinned in `tests/unit/test_migrations.py`). Every statement is a constant with bound parameters (no SQL built from
    strings). `UserStore.prefs` reads one person's rows; `set_prefs` refuses any key or value outside the sets and
    returns (key, from, to) of each change. Registered in `tb_common.erasure` as **not patient-linked**, with the
    reason. When an account is disabled its preferences are deleted with its sessions; enabled again it starts from
    the defaults (there is no account deletion in the console).
  - **The route:** `POST /account/prefs` (with the CSRF token) changes the signed-in person's own preferences only:
    the name is the session's, a posted name is ignored. A key not posted is left as it is; a value outside its set
    answers 400 with the error summary (the field macro, D-1376) and stores nothing. Each change writes one audit
    line `console.pref_set` with who, key, from and to (the console's audit family is `console`, D-488, so the
    review's `pref.set` is spelled `console.pref_set`); a save that changes nothing writes nothing. Every role
    reaches it (a CRO account too: it is added to the short list of a sponsor account's own pages beside
    `/account/password`); the API has no twin (listed with the reason in `tests/console/test_api_twin_check.py`, as
    `/role`: the API draws no page).
  - **The look:** `base.html` puts each value other than the default on `<html>` as `data-density`,
    `data-text-size` and `data-mode`; a person who chose nothing gets the page byte for byte as before. One block at
    the end of `console.css`: compact spacing (padding and gaps only; no target under 44 px, no button rule), the
    type tokens at 125 % and 150 %, and three colour modes as token sets on the root element: "light" and "dark" are
    the system's two palettes (a test holds them equal value for value), "contrast" a high-contrast palette.
  - **The language:** a stored language starts every new page session of the person (the sign-in page's choice and
    the browser's are used when it is "auto", as before); choosing it on the account page also switches the current
    session. The header's switch still changes the current session only. Mail languages are unchanged: the notices
    read their own setting (`notify_people`), never this table.
  - **The account page:** the "Language" card becomes "How your pages look" with the four fields through the field
    macro; the page uses the page header macro (D-1380). Its typed raw forms go from 2 to 1 (the ratchet line
    lowered), and it has one primary act now, so it leaves the `one_primary` list of
    `tests/unit/page_header_baseline_9k5.json`.
  - **Contrast in every mode:** `tests/unit/test_console_tokens_and_type.py` now also reads the three chosen modes:
    only `:root[data-mode="light|dark|contrast"]` may hold a colour beside `:root`, each sets every colour token,
    light and dark equal the system palettes, and the high-contrast mode passes every pair at 7:1 (text) and 4.5:1
    (the rest).
- **What was left out, and why:**
  - **Quiet hours** (item 5): left out by the owner's ruling. Quiet hours defer or suppress notices; a serious
    adverse event notice must never wait for a person's setting (FR-NOTIF-04 is H; the N1 SAE alert goes every day
    by design, D-764). Nothing here defers, suppresses or redirects any notice, and no preference is read by
    `console.notify`.
  - The rest of review 16's per-user row (home block order, saved views, column choice, notification rules, default
    study) belongs to other cards (10F-3, 10F-4) and is not built.
- **The invariant:** a preference may only choose among or hide what the role already shows. For every role (one
  column of the role walk per role: administrator, coordinator, PI, viewer, CRO with a monitor grant, steward,
  privacy office) and **every combination of the closed sets (96)**, the set of GET routes that answer 200 and the
  set of seeded patient pseudonyms each route renders are subsets of those with the default preferences; and no
  notice recipient list changes with any preference: the morning notices (N1 with its SAE alert, N2, the weekend
  digest) go to the same people with the same subject and words, whatever anyone chose.
- **Held by:** `tests/console/test_prefs_10f1.py`, the invariant in
  `test_no_preference_opens_a_route_or_shows_a_patient_value_the_defaults_do_not` and
  `test_no_sae_notice_recipient_changes_with_a_preference`; the form's failed-POST case `prefs` in
  `tests/console/form_cases_9k6a.py`; the role matrix, the declared route table and the API twin list
  (`tests/console/data/role_route_matrix.md`, `route_actions.yaml`, `test_api_twin_check.py`).
- **Not verified:** a native reader has not read the ja and zh-TW texts; the new modes were not looked at by a person
  on a screen (the contrast is computed, not seen).
