# D-987 Every cascade names its language; the measurement tools take it as an argument

- **Task:** a side finding of D-983 (#639, 2026-11-16), "FEAS never sets the cascade language", with the integrator's reading: build as proposed.
  - FEAS in the product counts in SQL (`feas_compute`) and builds no cascade. Only SCREEN builds a `CascadeConfig` in services, and it sets both `language` and `notes_language` (D-983).
  - The cascade's `purpose="feasibility"` runs are the measurement tools: `tools/scale_gate.py`, `tools/cascade_e2e.py`, and `tools/vec_parity.py` (the last as screening). They never set the language, so every note was read against the engine's default, zh-TW, whatever the notes were.

  **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - Each tool takes `--language`: `auto` (the default) or en, zh-TW, ja.
    - `auto` reads each patient's notes (D-983), with the tool's data's own locale as the fallback. The synthetic sites write zh-TW notes, so the fallback stays zh-TW. That is today's value, so no gate's result changes.
    - A named language is both the notes' language and the fallback.
    - Anything else is refused.
  - `matching.notelang.cascade_languages(setting, data_locale)` gives the pair.
  - `tools/g_probes.py` reads only a default from a `CascadeConfig` and now names its language too.
- **The guard:** `tests/unit/test_cascade_language_explicit.py` fails any `CascadeConfig(...)` in services, libs, tools or eval that does not pass `language=`. It also catches a call inside a child script held in a string, as `scale_gate`'s screen child is. The tests themselves are not scanned.
