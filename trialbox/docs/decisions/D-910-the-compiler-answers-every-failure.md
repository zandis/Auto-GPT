# D-910 The criteria compiler answers every failure

- **Task:** red of lane G's frozen-commit run (#639, 2026-11-16: criteria-compiler HTTP 500 on FEAS and APPROVE, 11 times, its log not kept); **Date:** 2026-11-16; **Status:** reserved
- **Decision:**
  - **A criterion that cannot run** (an age-or-sex atom with neither, `not` of two, `count>=` with no count, a score on a diagnosis) is kept as a person's check (`class: human`, flags `logic_invalid`, `needs_review`); the rest of the protocol compiles. Before, it stayed structured: its logic failed the whole compile, or went into the SQL as written (`()`).
  - **A criterion the IR refuses** is kept the same way (`ir_invalid`), with where it was refused, never the value.
  - **The approval's equivalence check:** a refusal by the FHIR server or the lake is a 422 at step `equivalence`, said by type and status, never the server's text.
  - **Every route** (`_answer`): a compile error or IR refusal is a 422 with its step and reason. Anything else is a 500 with an error id. The error's type and frames (never its text, D-557) go to the service log and to the audit chain (`compile.error`), which the box keeps.
- **Test:** `tests/unit/test_compiler_answers_every_failure.py`.
