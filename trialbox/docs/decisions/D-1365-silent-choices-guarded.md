# D-1365 Silent choices guarded: the chart-number rule, the health page's watcher, IT's root confirmation (10K-21)

- **Task:** lane K, plan 10 row 10K-21 (review 18, SO-21; section 1.8 rows W5, W6 and W7: three set-up choices that
  were silent or only a warning). · **Date:** 2026-11-19
- **Decision:**
  - **The chart-number rule (W6).** On a PRODUCTION site the settings wizard refuses to finish without an explicit
    rule: `asis` typed is an answer, Enter or no key is not (interactive: the question is asked again, its prompt
    says "required in PRODUCTION"; answers file: `not written: chartno_rule is required in PRODUCTION ...`). The
    wizard is told the environment by `--environment`; `deploy/install.sh` passes it (block `WIZARD-ENV`) as its
    `ENVIRONMENT` block decides it: `--environment`, a rehearsal's VALIDATION, a `TB_ENV` written before, else
    PRODUCTION (D-127). Not told (a test, `tools.box apply`, a person running the tool by hand), the wizard reads
    answers as before. An answered rule writes `TB_CHARTNO_RULE_ANSWERED=yes` beside `TB_CHARTNO_RULE`, so `doctor`
    can tell a chosen `asis` from a silent one.
  - **The box's first-run page** is the box's wizard: with the console on a PRODUCTION box (`TB_ENV`) it refuses to
    finish without a chart-number rule ("kept as written" chosen is an answer, "Not answered" is not), except where
    the page does not ask the rule (the box already holds patients, or that cannot be read: the box's rule stays,
    D-544, D-710). The rule's hint says it must be answered. One rule in `tb_common.box_answers.production_gaps`.
  - **The health page's watcher (W5).** A box's backup alert route is the health page (`TB_BACKUP_ALERT_ROUTE=
    health-page`, D-735; `tools/box/plan.py` always sets it). The first-run page asks who opens the health page
    every working day (`health_page_person`), required on a PRODUCTION box; the plan writes it as
    `TB_BACKUP_ALERT_WATCHER` in `deploy/.env`, beside the route. The terminal wizard refuses the route without a
    named person in PRODUCTION and warns elsewhere. **That refusal fires only for an answers file** (the route
    comes in its `env_extra`, as the box's plan writes it); a route an operator sets by hand in `deploy/.env` is
    caught by `doctor`'s `named_choices` WARN only. The name is shown where the route is shown: the backup install's
    note and `doctor`'s `backup` line ("<name> opens the health tab every working day"), or the next action when
    nobody is named.
  - **What is stored about a person:** a name only, as one printable line (no character `str.splitlines` breaks
    at, U+0085, U+2028 and U+2029 included, nothing that is not printable but the ideographic space U+3000; no
    quote, `$`, backquote, backslash or `#`; at most 100 characters), so `.env`, compose, the installer's shell and
    the Python readers read it as one value; both wizards use the one check (`box_answers.person_name`). It is kept
    in `deploy/.env` (root only, 0600) and the box's answers file (tmpfs, removed after the apply), as the wizard
    keeps the site's contact address. No mail address, telephone number or account is asked. The name appears in
    `doctor`'s detail and so in a support bundle's `doctor.json`, as the SAE office mailbox already does. A staff
    member's name is operational contact data, never patient data.
  - **IT's confirmation of the internal CA's root (W7).** With Caddy's own CA (`tls_mode internal`; every box) the
    guard is a `doctor` WARN in PRODUCTION, **not a refusal**: Caddy makes the root at its first start, after the
    wizard, so nobody can have pushed it before the install. The terminal wizard therefore records no confirmation
    (an answer `tls_root_confirmed_by` is not written, and it says so) and says the next action. The confirmation is
    recorded once the root exists: on the box's first-run page (served through Caddy, so the root is there; who,
    and the day it was given; a day to come is refused), or as `TB_TLS_ROOT_CONFIRMED_BY` and
    `TB_TLS_ROOT_CONFIRMED_ON` in `deploy/.env` after IT has pushed it. `doctor` WARNs until both are there.
  - **The environment the terminal wizard is told** is checked before the wizard runs: a value that is not DEV,
    TEST, VALIDATION or PRODUCTION stops `install.sh` with nothing written, so a typo cannot run the wizard unguarded
    and leave a `settings.yaml` the next run keeps. On the first-run page a PRODUCTION box whose patient check cannot
    be read cannot finish without the rule either (it says to have the database checked and load the page again).
  - **A site installed before (no silent change, no broken start).** The wizard runs only on a fresh install
    (`install.sh` keeps an existing `settings.yaml`), so an installed site's settings are not re-read by it. An
    answers file without the new keys reads exactly as before outside PRODUCTION (the legacy fixtures of 10K-1 keep
    their output). On a PRODUCTION box a new `doctor` check, `named_choices`, WARNs (never FAILs) for each of the
    three that is missing, with the next action: add `TB_CHARTNO_RULE_ANSWERED=yes` once the hospital says chart
    numbers are taken as written (another rule only on a box with no patient loaded); set
    `TB_BACKUP_ALERT_WATCHER`; set `TB_TLS_ROOT_CONFIRMED_BY` and `_ON` once IT has pushed the root. It PASSes
    outside PRODUCTION and says what is open.
- **A typed name never adds or changes a setting (review of #1175).** The names a person types (the health page's
  watcher, IT's confirmer) are checked where they enter, by an allow-list (`tb_common.box_answers.person_name`):
  letters, marks and digits of any script, single spaces and `. , - ( ) / ’ ・ ·`, at most 100 characters; a line
  break, a control character, a quote, `$`, a backquote, a backslash, `=` or `#` is refused. The `.env` writer
  (`tools.settings_wizard.env_text`, used by `write`) refuses every value, typed or not, holding a control character
  or a Unicode line break, or a leading or trailing space, and writes nothing then; `env_extra` applies the same to
  each value and the name check to the name keys. No reader unescapes, so a value is refused, never escaped.
- **Not in this card:** a console page or command to record IT's confirmation after the install (the next action is
  a line in `deploy/.env`); mail for the health page's watcher (a box has no mail agent, D-735).
- **Held by:** `tests/unit/test_silent_choices_guarded.py` (the terminal wizard, the installer's block, the box plan,
  the backup note, `doctor`); `tests/console/test_firstrun_silent_choices.py` (the first-run page, en, ja, zh-TW).
