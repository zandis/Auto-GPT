# D-1251 A pruned "More", one name per page and no job word on a clinical page, behind one flag (J-7)

- **Task:** card J-7 of lane J (plan 8, `docs/plan/44-plan-8-2026-11-17.md` section 4, area 0: "Prune "More"; one
  name per page; the steward's bar to four; no job words or variable names on clinical pages"; the journey review of
  2026-11-17, `docs/reviews/2026-11-17-journey-and-simplicity.md`, cards R17, R18 and R22: D-1 and D-M1 of section D
  and its table "One thing, several names"). It waited for the owner's decision 7, ruled yes in D-1067. The menus,
  the proposal and the lists were sent to the lane's coordinator before any product code and ruled there (Q1 to Q5
  and five further rulings). · **Date:** 2026-11-19
- **Decision:**
  - **One flag.** `layout.plain_menu` (`tb_common.flags.DECLARED`, values off/on, default off, no seed variable:
    changed only on `/ops/flags` with a reason, audited as every flag). It is read with `layout.phone_first` and
    `layout.home_today` in the console's one background read (`console.phone.LAYOUT_FLAGS`, one statement) and put in
    `request.state.plain_menu`. Off, every page is as before, byte for byte: each change sits between `{#J7#}` and
    `{#/J7#}` in a template, or is a `tp(key)` that is `t(key)` with the flag off.
  - **A menu is not a permission.** No route, guard, `permit` row, sign-in, audit event or mail changes. With the
    flag on, the role-by-route walk (every route, every column of the matrix) equals the committed table, and the V-2
    walk (signed out included) answers every route as its declared row.
  - **"More" pruned (R17)** (`templates/_nav_plain.html`). What leaves it, per role:
    - "Overview" (`/`, it opens the role's own home);
    - any entry the top bar already links: Users, the candidate registry, Reports for the CRO and the viewer, the
      steward's and the privacy office's registers and the audit trail;
    - the Admin page's own tabs (Health, Jobs, Data sources), reached from the Admin page;
    - for the clinical roles (the coordinator, the investigator, the viewer), the legacy pilot entries:
      - New request: linked from the feasibility reports page;
      - Compile a protocol: the opening page's button and the site wizard, as on master;
      - Consent explainer: linked from the study's IRB and consent form page;
      - Check one patient: linked from the weekly list and the candidate registry;
      - the cascade;
      - the test mailbox.

    The cascade is listed only where the synthetic site drop is mounted (a menu rule only; the page answers as before).
    The test mailbox is the administrator's only. "Runs" (`/jobs`) stays under "More" for the clinical roles: on master
    a run is reached by a click only from the confirmation after it starts and from that list. A person who starts a
    night's run must be able to see how far it is.
  - **The new links ask the page's own rule.** Each link that takes the place of an entry asks `may_act`, the rule its
    target page uses to offer its form or enable its button. So it is shown exactly where the page answers 200 *and*
    offers the account its action. A link never leads to a refusal or to a page with nothing to do.
    The administrator's and the steward's remaining entries keep the menu's old rule (`plain_menu.menu_shows`).
  - **The steward's bar has four entries** (D-104): Break-glass, Opt-out register, Data operations, Audit trail.
    The staff directory, clinical items, clinical conflicts and the flags page move under "More".
    For the owner: Clinical conflicts could take the place of Data operations; the flag is off by default, so this
    can change before anyone sees it.
  - **One name per page (R18).** A page's menu label, title and main heading come from one text key in each language
    (`plain_menu.SAME_FOR_ALL`). The renames:
    - "Runs" / 実行履歴 / 執行紀錄 for the list of runs;
    - "Feasibility reports" for `/reports`;
    - "My studies" for the coordinator's home;
    - "Feature flags" for `/ops/flags`;
    - "Check one patient" (no "(CASE)") for `/pilot/case`;
    - "Compile a protocol" and "Consent explainer" for their pages' own titles;
    - the candidate registry's one name;
    - the cascade's heading.

    Only words change; the Japanese and Chinese words are the pages' existing keys, or the catalogue's established
    words for a new string (`i18n_plain.py`).
  - **No job word or variable name on a clinical page (R22).** For every role:
    - the week list's "From the SCREEN run of …" becomes "List made …";
    - "Ruleset" becomes "Study criteria";
    - the request and registry pages lose FEAS, SCREEN, CASE and the mail commands;
    - the list of runs names a run's type in words;
    - the delegation log's history names each task;
    - the feasibility report's bare "hospital" is said in the page's language.

    For a clinical role only (`plain_menu.CLINICAL_ONLY`):
    - the footer drops "data class D0" and keeps the environment label (a person still sees a test box, and the
      test-site banner is on every page);
    - the SAE mailbox and ClinicalTrials.gov notices drop the setting's variable name. The administrator keeps the
      name, where it is set.

    A run's own page keeps its job id and type code. It is the record a person reports a problem by, reached from the
    list of runs, and the administrator's page.
    The audit table keeps each event's code beside its label (D-451).
  - **Decided by an allow-list.** A test renders every page a clinical role reaches (coordinator, study-scoped
    coordinator, investigator logged and not, viewer) in en, ja and zh-TW, with every catalogue text marked. Visible
    text outside the marks must be a data value: a number, a date, an id, a pseudonym, a study code, an account
    name, or a value the fixtures wrote. Catalogue text may hold no identifier-shaped word outside a list of plain
    acronyms (`tests/console/plain_text_walk.py`).
    One named exception (Q3): the study set-up page's typed category codes and EDC field names, shown in code style
    ("type this").
    The hand-fixed keys are pinned: no clinical page may show them again.
- **Why:** "More" was a drawer of everything (25 links for a coordinator on a study page); the steward had eight top
  entries; a page had up to three names; clinical people read job codes and environment variables. A flag because it
  changes what every role sees in the menu.
- **Not done here:** the opening page by study phase and removing "More" for clinical roles (R15), Help and Search
  (R20; the command field's examples keep their command words), `modules:` in settings (R40), routers per module
  (R42). Plain-English jargon in other catalogue texts is fixed only where listed (the test cannot see a plain word).
- **Proved by:** `tests/console/test_plain_menu.py`. It covers:
  - the flag and its one read;
  - one name for every menu entry of every role in three languages;
  - the ruled menus and the steward's four;
  - nothing unreachable;
  - each new link against its page's answer and action;
  - the cascade only when mounted;
  - the clinical walk in three languages with the banner and the pinned keys;
  - the flag off byte for byte;
  - both role walks with the flag on;
  - every combination with the other layout flags;
  - the plain keys in three languages.
