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
    `request.state.plain_menu`. Off, every page is master's, byte for byte, except two things on two pages. The flags
    page shows the flag's own card and its seed row. The audit trail holds the flag's seed event, so the chain hash
    of each later event and the "Older events" cursor differ. Each change sits between `{#J7#}` and `{#/J7#}` in a
    template, or is a `tp(key)` that is `t(key)` with the flag off.
  - **A menu is not a permission.** No route, guard, `permit` row, sign-in or mail changes. One audit event is added:
    the flag's `flag.seed` at the first start, as for every declared flag. With the flag on, two walks hold. The
    role-by-route walk (every route, every column of the matrix) equals the committed table. The V-2 walk (signed out
    included) answers every route as its declared row.
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

    The administrator's menu lists the cascade where the cascade says it works (`CascadeRuns.available`: the synthetic
    site drop is mounted). It is a menu rule only; the page answers as before.
    The test mailbox is the administrator's only. "Runs" (`/jobs`) stays under "More" for the clinical roles: on master
    a run is reached by a click only from the confirmation after it starts and from that list. A person who starts a
    night's run must be able to see how far it is.

    **Still allowed, no longer linked** (for the owner). The routing table is unchanged, so each of these pages still
    answers the account as on master by its address. No menu entry or page links it any more:
    - the cascade, for the coordinator (it stays in the administrator's menu);
    - the test mailbox, for the coordinator, the investigators, the data steward and the privacy office;
    - New request and Check one patient, for the investigator in no delegation log: both pages offer it nothing (Q4).

    **Menu entries that answer 403, as on master** (listed, not new). The investigator in no delegation log still has
    "This week's patients" and a study's candidates, referrals, data entry and trial-record differences in its menu,
    and each refuses it. Master's menu links them the same way; a later card can hide them by the pages' own rule.
  - **The new links ask the page's own rule.** Each link that takes the place of an entry asks `may_act`, the rule its
    target page uses to offer its form or enable its button. So it is shown exactly where the page answers 200 *and*
    offers the account its action. A link never leads to a refusal or to a page with nothing to do.
    The administrator's and the steward's remaining entries keep the menu's old rule (the old menu's conditions).
    The factoring changes no page: each role is offered each action exactly as on master, with the flag off and on.
    No link is shown to an account the old menu did not show the entry to.
    A page carrying a link adds reads only for an account whose role may start a run in some study
    (`tb_common.authz.role_allowed`) and that does not prepare requests: the investigator. It reads the list of
    studies' criteria once per page view (`backend.rulesets`: id, version, status, kind; no patient data; the list
    the target page reads for that account). It also reads its standing in the delegation log of each approved study
    it sees, once per study and page view (`Helpers.stand`). An account that prepares requests, or whose role may
    never start a run, reads nothing more. The action pages read the list once, as on master.
    If the criteria list or the delegation log cannot be read, the link is not shown and the page answers as it does
    with the flag off.
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

    A link inside a page says the same name as the page it opens: its main heading without data values. A link to a
    section or an action says that section's heading on the target page, or, for a tab, the tab's own label (the
    coordinator's review). The renames:
    - "Mail notices" for the notification settings link;
    - "Users" and "Add an account" for the administrator's links to the users page;
    - "Compile a protocol" for "Send in a protocol" and "Send the protocol";
    - "Sign-in and recovery" for the sign-in links;
    - "Overview" for "Services and models";
    - "Site set-up" and "Set up step by step" for the site tabs "Readiness" and "Step by step";
    - "Feasibility report" for "Open report";
    - "This week's patients" for "Open this week";
    - "Who to screen" for "Choose the whole hospital under Who to screen";
    - the operations card's "Open" says the section it opens.

    The next-step button on a study card ("Go") says the page or section it opens (`plain_menu.NEXT_GO`). The week
    list's notice that the delegation log is due is text, followed by a link "Monthly comparison".

    A link that carries a data value names that thing, not a page: a person, a study code, an id, a count. It is not
    held to this rule. The registry's source column says the run's type ("Screening", "Check one patient") and links
    the run by its id, as the list of runs does. "Weekly PI list" was a second name for "This week's patients" and is
    gone; the registry's texts say "This week's patients".

    Only words change; the Japanese and Chinese words are the pages' existing keys, or the catalogue's established
    words for a new string (`i18n_plain.py`).
  - **No job word or variable name on a clinical page (R22).** For every role:
    - the week list's "From the SCREEN run of …" becomes "List made …";
    - "Ruleset" becomes "Study criteria";
    - the request and registry pages lose FEAS, SCREEN, CASE and the mail commands;
    - the list of runs names every run type in words. The list of types is the contract's own (`tb_contracts.Job.type`;
      a test keeps it equal to the orchestrator's `scenarios.registry`). A type the console does not know is "Other run",
      never its code;
    - the delegation log's history names each task;
    - the feasibility report's bare "hospital" is said in the page's language.

    For an account that does not keep the box's internal names (`plain_menu.CLINICAL_ONLY`):
    - who keeps them is a `permit` question, never a role name: `audit.provenance`, held by the administrator, the
      data steward and the privacy office;
    - the clinical roles and the CRO read the plain sentence;
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
  - one name for every menu entry of every role in three languages: the label *is* the main heading and the title;
    the entries that answer 403 are listed;
  - every link inside the pages each role's menu opens, in three languages: it says its page's or section's name;
  - the ruled menus and the steward's four;
  - nothing unreachable, the site drop mounted, except the named "still allowed, no longer linked" pairs;
  - each new link against its page's answer and action;
  - each role's actions as on master;
  - the reads a page with a link adds, and a failing delegation log or criteria list;
  - the cascade exactly when it says it works;
  - every run type named in words in three languages;
  - the clinical walk in three languages with the banner and the pinned keys;
  - the flag off byte for byte against the templates without this card's parts (kept on every later commit);
  - both role walks with the flag on;
  - every combination with the other layout flags;
  - the plain keys in three languages, and the capability that keeps the internal names.

  Against master's rendered bytes: `python -m tests.console.j7_master_bytes`. It renders every column of the matrix,
  three languages, the pages of the byte test plus the audit trail and the administrator's home. It renders once from
  a worktree of the merge base and once from this checkout, each in its own process, and allows only the flag's own
  seed as named above. It is a script, not a test of the suite: a CI shard checks out one commit, and once this is
  merged master is this code. The pull request reports its result for each head.
