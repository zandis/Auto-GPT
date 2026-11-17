# Roles, surfaces and scenarios: the people, the screens and the kinds of study (lane J, job B-2, 2026-11-17)

**Reader:** the owner first (the one-page summary). Then the builders (sections 1 to 4) and plan 9 (section 5).

**What was analysed:** master `15108f46` (train 76). Read: the permission matrix, the console's code, templates and
stylesheet, the Windows installer and its owner pages, the orchestrator's reimbursement path (NAV, TWPAS, SUBMIT),
the specification's intended-use statement, the role guides and the decisions D-877, D-1063 and D-1151. Seen: the
journey review's screenshots (`docs/reviews/img/`) and other agents' screenshots of the seeded synthetic box under
`/var/tmp/trialbox-0/*/shots/` (1280 and 390 px; en, zh-TW, ja). No box was seeded or started for this page. No
product code was changed. Public and synthetic data only.

**What this page does not repeat.** The journey review (`docs/reviews/2026-11-17-journey-and-simplicity.md`, cited
as **R** with its finding ids A-1 to H-M7 and its cards R1 to R58), the life-cycle walk
(`docs/handover/life-cycle-walk-findings-2026-11-17.md`, **F-01 to F-21**), plan 8 (`docs/plan/44-plan-8-2026-11-17.md`)
and B-1 (`01-system.md` on `agent/B1-root-system`, the data, stores and model). Where this page agrees with one of
them it cites the id and adds only what is new.

**In hand in lane J** (cited as "in hand", not proposed again): one status for a person; two people lists
(Candidates, Participants); a phone-first layout behind a flag (web manifest and icons, no service worker); a home
page by role and study phase behind a flag; modules a site switches on; one Help.

**How every claim is marked.**

| Mark | Meaning |
| --- | --- |
| **[R]** | Read: the file and line follow in backticks |
| **[Seen]** | Seen in a screenshot (the path follows) or a page opened |
| **[S]** | Source: a public link follows; it was opened for this page |
| **[M n]** | Measured: row n of the measurement log (section 6) |
| **[O]** | Opinion: the analyst's judgement, to be argued with |
| **not verified** | Could not be checked here; section 7 lists each |

---

## Summary (one page, plain words)

**The product already holds the right model of roles; what it lacks is the hospital's real people and the moments
when they change.** [O]

1. **One doctor in many studies already works.** A doctor is one "investigator" account; whether he is PI, a
   sub-investigator or nobody in a given study is decided per study by that study's delegation log, with dates
   [R `libs/tb_common/authz_matrix.yaml:109-110`; `services/console/teamstore.py:398-401`]. That is the right design
   and it needs no "acting role". What is missing is a way to *see* it: the top bar says "investigator (PI / sub-I)"
   on every page (B-9 of R), and nothing lists "your role in each study".
2. **Production's "one account, one role" is right, and hospitals will strain against it in three places**: the
   research nurse who is also the unit's data steward; the IT person who is also the privacy officer; the small
   hospital with one coordinator who also keeps the opt-out register. The two-person rule compares *user names*
   [R `services/console/account_rules.py:75-91`], so the obvious workaround (a second account for the same person)
   silently defeats it. Bind each account to one person in the staff register and refuse a confirmation between two
   accounts of one person. (Section 1.3.)
3. **Cover and departure are half-built.** The delegation log has start and end dates and "the last PI entry active
   that day" wins [R `teamstore.py:398-401`], so a covering PI can be entered; accounts have end dates. But nothing
   names who covers, nothing warns that a PI's entry ends next week, a coordinator's open tasks belong to no one
   (every coordinator sees every study, `authz_matrix.yaml:109`), and the IRB notice of a PI change is not linked.
4. **Five people the product does not know**: the pharmacist (study drug, and the reimbursement scenario), the
   research nurse as distinct from the coordinator, the laboratory or biobank, the sponsor's medical monitor, and the
   patient. Only two need an account (pharmacist; later a biobank keeper). The others need a printed or mailed
   output, not a log-in. (Section 1.2.)
5. **Surfaces: keep one web console; make it installable; do not build a native app.** The box is a server inside
   the hospital; a phone reaches it only on the hospital network. An installable web app (manifest, icon) costs
   almost nothing and is in hand. A service worker adds offline pages a clinical record should not keep, and push
   needs the box to call Apple's or Google's servers. The hospital mail on a managed phone already *is* the push
   channel: the morning mails exist [R `services/console/notify.py:1-23`]. Biometric re-authentication is available
   to the web through passkeys (WebAuthn) without an app [S firt.dev]. A native app adds a second code base,
   store review or MDM work and a validation burden, for nothing the web cannot do here. (Section 2.)
6. **The owner's "no separate app" ruling already settles the phone question**; this page finds no fact that should
   reopen it. It does add one thing he has not ruled on: a desktop "app" on Windows and Mac is the *same* installed
   web page (Edge "Install", Safari "Add to Dock"), free, and worth one line in the guides. [S; O]
7. **User assistance: the pieces exist and are scattered.** Help, "Ask", a command field, seven role guides, a
   glossary for patient-facing roles, good empty states. Four accessibility defects are concrete: input borders at
   1.37:1 (WCAG 1.4.11 needs 3:1), a dark-mode amber row where links fall to 2.6:1, a ten-minute lock with no warning
   (WCAG 2.2.1), and errors not tied to their fields (2 templates of 133 use `aria-invalid`). (Section 3.)
8. **Reimbursement for biologics is not a new idea in TrialBox; it is an old one with no screen.** The orchestrator
   already has NAV ("NHI reimbursement navigation"): likely eligible, renewal due, documentation gaps, maybe
   ineligible, an application draft per patient, a TWPAS prior-authorisation bundle, and a physician's SUBMIT to the
   NHI [R `services/orchestrator/scenarios/nav.py:1-11`; `submit.py:1-15`]; two synthetic rule sets exist, RA
   biologics and osimertinib [R `rulesets/RA-BIO/manifest.yaml:1-3`]. It runs by mail command; no console page shows it.
9. **And it contradicts the product's own intended use.** The normative statement says TrialBox "is not intended
   to … inform an individual patient's clinical management" [R `spec/v4/01_constraints_product_experience.md:293-295`];
   the regulatory position says it "does not recommend treatment" [R `docs/plan/design/16-regulatory-position.md:28`].
   A list of patients "likely eligible" for a biologic, with a pre-filled application, informs that patient's
   treatment. Either NAV is fenced as a separate product with its own intended use and device analysis, or it is
   left out of release 1.0. This is the owner's decision; it is the most important point of this page. (Section 4e.)
10. **The common core is real**: criteria as rules over the record, a list with evidence, a person's decision,
    tasks and hand-overs, a schedule of follow-ups, an audit trail. "Study type" (per study) is the right switch for
    *how* a study runs (contact or not, consent or waiver, safety rules, device or drug); "module" (per site) is the
    right switch for *what the site bought* (feasibility, screening, conduct, EDC, reimbursement). Today study type has
    three values (trial, registry, observational) and drives almost nothing beyond the SAE rules
    [R `services/console/sitestore.py:40`; `services/console/study_setup.py:106`]. (Section 4, common core.)

**Size of the work:** 31 cards, 14 small, 12 medium, 5 large (section 5). Four can start now and need no ruling.

---

## 1. Every role and every change of role

### 1.1 The roles the product knows

The matrix has seven roles [R `libs/tb_common/authz_matrix.yaml:30`]. "Investigator" splits into PI and
sub-investigator per study through the delegation log (`authz_matrix.yaml:109-110`, conditions `logged_pi`,
`logged_tick`). The table follows a study from feasibility to archive; R section B has the first five minutes and
the clicks per role, which are not repeated.

| Role (on screen) | What they do across a study's life | Where they enter | What they hand to whom |
| --- | --- | --- | --- |
| **Administrator** (IT) | Install, update, back up, accounts, network, certificates. Never a patient row (D-280) | `/admin`, the morning health mail | Account opened → the steward confirms (D-719); break-glass grant → the steward reviews |
| **Coordinator** (CRC) | Feasibility request, study set-up, site fields, runs, contact outcomes, consent and enrolment, visits, AEs, deviations, EDC pre-fill, the monthly delegation-log check, study state and close | `/home` "My work"; the daily digest N2 [R `notify.py:8-12`] | Criteria ready → PI approves; SAE saved → PI acknowledges; referral → treating doctor (answer recorded by the coordinator) |
| **Investigator as PI** | Approves the criteria; marks Approach / Need info / Not suitable; acknowledges SAEs; keeps the delegation log; grants monitor visits; switches EDC pre-fill on; records IRB text coverage; may reopen a same-day close | The week list; the morning mail N1 | Approach → a dated task for the coordinator; monitor grant → CRO |
| **Investigator as sub-I** | What the PI ticked: screen, approach, refer, enter data, run (`authz_matrix.yaml:111-130`) | The same week list | As the PI, within the ticks |
| **Data steward** | Data nights (accept or hold), opt-out register, staff directory, break-glass reviews, account confirmations, the study's first PI entry, the not-matched check | Break-glass reviews (R, B) | The PI entry → the PI can then keep the log; a held night → the administrator |
| **Privacy office** | Opt-out register, staff directory, audit trail (`authz_matrix.yaml:694-711,793`) | No seeded account (R, B) | A patient's request → today nobody (R, C-3) |
| **Viewer** (research office) | Feasibility reports and the office's yearly counts, small cells hidden (`authz_matrix.yaml:98-106`) | `/reports` | Nothing; reads only |
| **CRO monitor** | Sponsor copy of reports; under a PI's grant, the enrolled subjects read-only and a visit record (`authz_matrix.yaml:757-783`) | `/reports`; after a grant a banner | Monitoring visit findings → the PI (no thread back; R, A-M5) |

Three things the table shows that R did not say:

- **Two people may set up and close a study, but only one may open it.** `study.state` is coordinator or PI
  (`authz_matrix.yaml:158-161`); `study.reopen` is PI only. Good. But the SAE type for a study is asked only when a
  coordinator opens the state page (F-14). [R]
- **The viewer is the research office in practice, but its label says "viewer (read only)"**
  [R `services/console/i18n.py:34`]. A hospital will call it the research office (研究室, 臨床試驗中心). [O]
- **The Japanese label for the investigator is 治験責任医師／分担医師** [R `services/console/i18n.py:429`]: these are
  words for a drug trial under the PMD Act (治験). For a non-治験 clinical research study the words are
  研究責任者／研究分担者. Every scenario in section 4 except the drug trial meets the wrong word in Japanese. [O]

### 1.2 The people the product does not yet know

| Person | What they do in real hospital life | Today in TrialBox | What they need | Account? |
| --- | --- | --- | --- | --- |
| **Pharmacist** (investigational drug pharmacist; in reimbursement, the dispensing pharmacist) | Receives, stores and dispenses study drug; drug accountability; temperature logs; checks a biologic's approval before dispensing | Nothing; R A-M6 says study drug is outside TrialBox | For a trial: a signpost only (R13). For reimbursement (4e): the approval status and expiry of each patient's prior authorisation, read-only | Only with the reimbursement module [O] |
| **Research nurse** | In Taiwan and Japan often the same job as the CRC (研究護理師, 治験コーディネーター); in some units a nurse does consent support, sampling and visits while a separate CRC does paperwork | The coordinator role covers it | Nothing new as a role; a "Sampling and visits" view of the participant is enough | No: coordinator [O] |
| **Laboratory or biobank** | Receives samples, logs them, stores and releases them under the consent's scope | Nothing; no sample form among the seven built-in forms [R `services/datacore/builtin/forms.csv`, form names counted, M 4] | For a biomarker study (4b): a sample log per participant and the consent scope per sample | Later; first as an export the lab reads [O] |
| **Sponsor's medical monitor** | Reviews SAEs and eligibility questions for the sponsor | Not a user; the SAE register records "sent to sponsor" (`ae_rep_sponsor`) | Nothing in the box: the box never sends patient-level data to the sponsor except through the EDC. Keep it so | No |
| **The treating doctor** (not on the study team) | Agrees or declines to introduce a patient | A referral row; the coordinator records the answer (`authz_matrix.yaml:739-742`) | The answer to come back to the investigator (R, B-6) | No: a printed or mailed referral is right [O] |
| **The patient** | Consents, withdraws, opts out, asks what is held | Recorded by staff; no receipt (R, C-2, C-3) | A printed receipt of an opt-out and of a withdrawal's data-use answer | No (ePRO declined, plan 8 section 2) |
| **IRB / ethics committee office** | Approves, amends, receives SAE and deviation reports; in an investigator-initiated study it is the main counterpart | A record per study (`irb.edit`), no output for it | An "IRB pack" export: approvals, versions, SAEs and deviations reported, dates (section 4a) | No |

### 1.3 Changes of role in real hospital life

**One person, many roles.** A rheumatologist is PI of an RA trial, sub-investigator of an AD trial and the treating
doctor of patients on a third. In TrialBox this is one investigator account; each study's log decides
(`authz_matrix.yaml:109-110`), and as a treating doctor he is not a user at all, which is right (he answers a
referral). No acting role is needed for this, on a test box or a real one. [R; O]

**What a hospital will ask for** [O, from the field-research review `docs/reviews/2026-11-08-field-research-tw-jp-sites.md`
and the role list above]:

1. "Let our research nurse also keep the opt-out register" (coordinator + steward).
2. "Our IT security officer is also the privacy officer" (admin + privacy).
3. "Our only research-office clerk also coordinates one study" (viewer + coordinator).
4. "The PI is away for three weeks; Dr B covers" (PI cover).
5. "Our CRC left; the new one starts Monday" (departure mid-study).
6. "The professor wants to see everything, including the IT page" (PI + admin).

**What the separation of duties allows.** D-280 keeps the administrator off patient rows; D-380 keeps the opt-out
register with the steward and privacy office; D-719 needs a second person for protected accounts
[R `authz_matrix.yaml:23-27`]. From these:

| Combination | Allowed? | Why |
| --- | --- | --- |
| coordinator + steward | **No** [O] | The steward reviews break-glass and keeps the opt-out register over the patients the coordinator works on; the person would review their own access |
| admin + privacy | **No** [O] | The privacy office reads the audit trail that records the administrator's break-glass |
| viewer + coordinator | **Yes, as the coordinator only** [O] | The coordinator already has `report.office` (`authz_matrix.yaml:98-101`); the viewer adds nothing |
| PI + admin | **No** (D-280) | The administrator must not hold patient rights |
| investigator + coordinator | **Yes, by delegation** [O] | A doctor who does his own coordination is a PI with every task; he does not need the coordinator role except for set-up, which the hospital can give to another coordinator |

**What the product does today with each transition.**

| Transition | What the product does today | What is missing |
| --- | --- | --- |
| A doctor is PI on study A, sub-I on study B | Per-study rights from the delegation log; the refusal sentences are clear (R, B "Keep") [R `authz_matrix.yaml:109-130`] | A line "Your role: PI in RA-01, sub-I (screen, approach) in AD-02" on the home page and the account page (R, B-9 asks for the label; this asks for the list) |
| A covering PI for three weeks | A second PI entry with start and end dates; the last active one wins [R `teamstore.py:398-401`]; the steward writes a study's first PI entry (`authz_matrix.yaml:721-724`) | A "Cover" action that writes the covering entry with end date in one step; a banner "Dr B covers until 2026-12-08" on the study; a reminder to the coordinator to file the IRB notice; the mails N1 go to the covering PI for those dates (not verified that they do) |
| PI on leave, no cover named | The SAE stays unacknowledged; the mail N1 keeps going to the absent PI [R `notify.py:14-16`] | A rule: an SAE unacknowledged for N days names the study's sub-investigators and the coordinator; the PI's absence can be recorded |
| A coordinator leaves mid-study | Their account gets an end date or is disabled; their tasks are not theirs: every coordinator sees every study (`authz_matrix.yaml:109`) | That property is good for continuity and bad for accountability: tasks have no owner, so "who was meant to call patient X" has no answer. Add an optional owner per study ("lead coordinator") and per task, with "reassign all of X's tasks to Y" on departure. The delegation log's CRC row gets its end date in the same step |
| A sub-I's delegation ends | The entry's end date stops the rights that day (`teamstore.py:238-240`) | A warning on the PI's page two weeks before an entry ends; today nothing says it |
| The PI changes for good | A new PI entry; the old one's end date | The same as cover, plus the IRB amendment link (R, A-M3) and the sponsor's notice as a task |
| Test box: one tester, many roles | The acting role, chosen at sign-in and switched in the top bar, audited, refused on VALIDATION and PRODUCTION boxes [R `services/console/acting.py:15-18`; D-1151] | Nothing for its purpose. Keep it test-only |
| Production: one person, two accounts | Allowed by nothing and refused by nothing. The two-person check compares user names only [R `services/console/account_rules.py:75-91`]; the audit notes who opened the confirming account, which helps after the fact | **Bind every account to one staff-register person** (`teamstore.py` already has a staff row with a `username`); refuse an account request confirmed by another account of the same person; show the person's accounts together on the steward's page |
| Production with the hospital's directory (OIDC) | A person whose groups map to two roles is refused [R `services/console/oidc.py:9-12`] | The refusal is right; the page should say which two groups clash and that IT must choose |

**The acting role versus production.** D-1063 and D-1151 settle it: the acting role exists only on a test box
[R `docs/decisions/D-1151-the-role-at-sign-in.md`]. This page agrees and adds the reason in hospital terms: in
production, "switching role" is the same as "one person holding two duties"; GCP and the hospital's own
access-control rules (Taiwan's electronic medical records regulation, Art. 3(1)(2), asks for control of who may make,
read, copy and send a record [S https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020121]) want that to be a decision
on paper, not a drop-down. What a hospital needs instead is items 4 and 5 of the list above (cover and departure),
which are per-study changes of *duty*, not of role. [O]

---

## 2. Every surface

### 2.1 What exists

- **The server is the box.** On Windows the box *is* a workstation: the models and the console run on its graphics
  card, and the trial team may also use the PC as a desktop [R `docs/handover/desktop-use.en.md:5-6`]. The console
  is served from WSL2 through one port-proxy rule on port 443 [R `deploy/windows/console-proxy.ps1:5-10`]. On Linux
  the box is a server in the hospital network. Either way every other device reaches TrialBox in a browser.
- **The console is server-drawn HTML**, one stylesheet of 561 lines and one small script that only adds
  conveniences ("every page works without it") [R `services/console/static/console.js:3`; M 2].
- **Phone layout:** no sideways scroll on 30 pages; 44 px targets; the PI's evidence sheet is the best phone screen
  (R, E). Behind lane J's flag the week list shows the first patient on the first phone screen [Seen
  `/var/tmp/trialbox-0/j3/shots/week-pi-after-on-en-390.png`]; the coordinator's home still opens on two SAE cards
  [Seen `/var/tmp/trialbox-0/lanej-tools/shots/master-crc-_-zh-TW-phone.png`].
- **Notifications today are mail**: N1 to investigators, N2 to coordinators, the administrators' health mail;
  pseudonyms only, internal addresses only [R `services/console/notify.py:1-23`].
- **Sessions:** a ten-minute idle lock and an eight-hour lifetime; an hour for directory (OIDC) sessions
  [R `services/console/auth.py:70-71`].

### 2.2 What each kind of "app" adds, and what it costs

The same facts apply to every surface below.

| Kind | What it adds over the page | What it costs | Fits TrialBox? |
| --- | --- | --- | --- |
| **The page in a browser** (today) | – | – | Yes |
| **Installable web app, no service worker** (manifest, icons, theme colour) | An icon on the home screen, Dock, Start menu or taskbar; opens in its own window without browser bars. iOS 26 opens every site added to the Home Screen as a web app even without a manifest [S https://firt.dev/notes/pwa-ios/]; macOS Safari "Add to Dock" copies the login cookies and keeps other storage separate [S https://webkit.org/blog/14445/webkit-features-in-safari-17-0/]; Edge installs to Start and taskbar [S https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux] | A manifest and icons (in hand). The box's certificate must be trusted by the device (the hospital's CA pushed by MDM) or the browser refuses to install [O]. Edge's installed web apps are not supported under FSLogix profiles, common on hospital virtual desktops [S Microsoft Learn, above] | **Yes**: cheap, no new risk |
| **Installable web app with a service worker** | Offline pages; Web Push and the badge count (iOS 16.4+, only when installed on the Home Screen) [S https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/] | (1) An offline copy of clinical pages in the device's cache: patient data at rest on a phone. (2) Push goes through Apple Push Notification service or Google's service: the box must call out to `*.push.apple.com` or Google, through the egress rules that today allow only mail, NHI and a few named hosts [R `spec/v4/04_architecture_llm_hermes.md:35`; S WebKit, above]. (3) The service worker becomes part of what must be validated. (4) On iOS no background sync [S firt.dev] | **Not now** [O]. The cache is exactly what a clinical box should not leave on a phone; push duplicates the mail the phone already receives |
| **Wrapped app** (a web-view shell; Android Trusted Web Activity, iOS WKWebView) | A store listing or an MDM-pushed app; on Android the shell renders the site in Chrome with Digital Asset Links proving the same owner [S https://developer.chrome.com/docs/android/trusted-web-activity] | A signing identity per platform; Apple's custom-app route still needs App Review and App Store Connect, then Apple Business Manager and MDM at the hospital [S https://developer.apple.com/custom-apps/]; Google's managed Play allows private apps per organisation [S https://support.google.com/googleplay/work/answer/9146439] (web apps there: not verified). The shell adds nothing the installed web app lacks for TrialBox | **No** [O] |
| **Native app** | Push through the OS; biometrics; the camera; offline reading; a smoother list | A second code base in two languages (Swift, Kotlin) or one framework; store review or MDM per hospital; its own validation (GAMP category, test scripts, release records); data at rest on the device needs encryption and remote wipe; **and it still reaches the box only on the hospital network or VPN** | **No** [O] |

**Each native feature, checked against the web.**

| Native feature | Needed by TrialBox? | Without an app |
| --- | --- | --- |
| Push for an SAE or a task | The PI must learn of an SAE the same day | The mail N1 already goes out on any working day an SAE waits [R `notify.py:14-16`]; on a managed phone the mail app notifies. Add: one short mail at once when an SAE is saved (today it waits for the next N1), carrying a pseudonym and a link, nothing else [O] |
| Biometrics at signature | The EDC signature asks for the password again [R `services/console/templates/edc_review.html:5-7`] | Passkeys (WebAuthn) work in Safari since iOS 14.5 and in every current browser [S firt.dev]; a platform authenticator gives Face ID or Touch ID on the same web page. A second factor exists (TOTP). Size: M, and a Part 11 argument to write [O] |
| Camera for consent documents | The consent record is a record of the facts (date, version, who, witness), not a scan [R `services/datacore/builtin/forms.csv:11-26`] | **Do not add scans.** A scan of a signed consent holds the patient's name and signature, which the box does not otherwise store (pseudonyms only). The signed paper stays in the site file. A browser file input with `capture` would work if ever needed [O] |
| Offline reading | A PI between clinics on hospital Wi-Fi | Not needed inside the hospital; outside, the box is unreachable by design. An offline copy is a liability [O] |

**The box is reachable only inside the hospital.** This settles more than any feature: a phone app outside the
hospital network can show nothing but what it cached. Hospitals in Taiwan and Japan reach internal systems from
outside through a VPN if at all; Japan's guideline for medical information systems (第7.0版, June 2026) is the
reference for remote and mobile access [S https://www.mhlw.go.jp/stf/shingi/0000516275_00006.html] (its mobile
clauses not verified). In the US the Security Rule makes encryption of ePHI and automatic log-off "addressable"
safeguards [S https://www.law.cornell.edu/cfr/text/45/164.312]; a proposed rule of January 2025 would make more of
them required (not verified). Taiwan's EMR regulation asks for encryption in transit and identity checks before a
record is made [S law.moj.gov.tw, above]. None of these forbids a phone; all of them make data at rest on a phone the
hospital's problem, which the web console avoids.

### 2.3 Recommendation per surface

| Surface | Who, for which task | Recommendation | What must be true first |
| --- | --- | --- | --- |
| **Server console in a browser** (any desktop) | Everyone; all desk tasks: set-up, delegation log, criteria approval, EDC review, data nights, accounts, audit | **The one product surface.** Keep it server-drawn | – |
| **Windows desktop** (the box PC and other hospital PCs) | Coordinators on the box PC; everyone on clinic PCs | **The installed web app from Edge** (Start menu, taskbar); one paragraph in each role guide. No separate Windows app | The manifest (in hand); the box's certificate trusted by hospital PCs; a note for virtual desktops (FSLogix) |
| **Mac** (research office, some PIs) | Reports, the week list | **Safari "Add to Dock"** or the browser; nothing to build | Same certificate rule |
| **iPhone, iPad** | PI: the morning list, evidence, marks, SAE acknowledgement; coordinator: contact outcomes, look-up, the task list (R, E table) | **Installable web app without a service worker**; the mail app as the notification channel | Phone-first pages (in hand); the hospital's Wi-Fi or VPN reaches the box; MDM pushes the hospital CA; the idle lock warns before it locks (section 3) |
| **Android phones, tablets** | The same | The same | The same |
| **Native or wrapped app** | – | **Not for release 1.0, and not on any planned path.** Re-open only if a hospital requires an MDM-listed app *and* a sponsor pays for its validation | A hospital's written requirement |

**What the owner's "no separate app" ruling already settles** (plan 8, section 2 "Out"): the native and wrapped rows
above. What it does not settle, and this page recommends: the installable web app on every platform (in hand), no
service worker, mail as the push channel, and passkeys for re-authentication later. [O]

---

## 3. User assistance

### 3.1 What exists

| Aid | Where | State |
| --- | --- | --- |
| Help ("?"), "Ask", the command field, "More → Help" | Header of every page [R `services/console/templates/base.html:26-33`] | Four doors; the command field understood 15 of 50 phrases (R, B-5). One Help is in hand |
| Role guides | `docs/guides/<role>.<lang>.md`, 7 roles × 3 languages, made from the page help [R `docs/guides/coordinator.en.md:1-3`] | Good and printable; no sub-investigator guide (the investigator guide covers both) |
| Glossary | `life.gloss.*`, for roles that see patients [R `services/console/guides.py:5`] | Trial words only; not the system words on screen (R, D-3) |
| Empty states | e.g. a study with nothing yet | Good: one sentence, one button (R, D "Keep") |
| Undo | Every PI mark | Good. Withdraw and close have neither undo nor a confirm (F-11, F-15) |
| The testers' pages | `docs/handover/new-study-walk.{en,zh-TW,ja}.md` | A walk of a new study; stops before conduct (life-cycle walk, "The testers' pages") |
| Refusal pages | 403 with the role switch on a test box | Wrong advice in places (R, B-8) |

### 3.2 What modern practice adds, sized for an offline clinical product

| Practice | What it means here | Already in hand or in R? | New here | Size |
| --- | --- | --- | --- | --- |
| Task-first home | "Needs you today", at most five | In hand | – | – |
| Inline explanations of system words | A dotted underline on "pseudonym", "rule set", "screening number", "delegation log" that opens a two-line definition, from the glossary, in the page's language, no script (`<details>` or `<abbr title>`) | Glossary exists (R, D-3 asks to extend it) | Put it on the page, not only in Help; 19 `title=` attributes exist in 133 templates [M 2] | S |
| Checklists per phase | Start-up (R9), close (R5) | In R | A checklist for **each scenario type** (section 4): a registry study's start-up has no SAE rules and no delegation-log chores | M |
| First-run tours vs guides | Tours (overlays pointing at buttons) need script, break on every layout change and are skipped by busy clinicians | – | **Prefer guides and a "first week" card** on the home page per role ("Your first week as a PI: approve the criteria; open your week list; mark one patient"), ticked off as done, then gone. No overlay tours [O] | S |
| Undo instead of confirm | Undo where the act is reversible (marks, contact outcomes, a visit ticked); a confirm page where it is final (withdraw, close, SAE acknowledgement) | R E-3, F-11, F-15 ask for confirms | State the rule once in the house style: "reversible → Undo, final → a confirm page that names the consequence" | S |
| Search over everything | One field that finds a page, a participant by screening number, a patient by pseudonym (for roles that may), a study, a glossary word | One Help in hand; R B-5 | Participant and pseudonym look-up from the same field (F-18 had to type `?list=all&pid=`) | M |
| Errors that say what to do | Every error: what happened, whether anything changed, what to do next, whom to ask | Install refusals already end "nothing was changed" (R, H "Keep") | Tie field errors to their fields (`aria-invalid`, `aria-describedby`): 2 of 133 templates do it [M 2] | M |
| The three languages | All aids in en, zh-TW, ja | Yes for pages and guides | The Japanese role words for non-治験 research (section 1.1) | S |

### 3.3 Accessibility (WCAG 2.2 AA), from the stylesheet and templates

Contrast was computed from the colour tokens of `services/console/static/console.css:3-11` with the WCAG formula
[M 1]. Text contrast is good: ink on background 14.6:1 (light) and 15.0:1 (dark); muted text 5.4:1 and 8.2:1; links
6.0:1 and 7.3:1; the coloured pills 5.7 to 8.9:1. The focus ring is 3 px of the accent colour, 6.0:1 and 7.3:1
against the background [R `console.css:58-59`]. A skip link exists [R `base.html:13`] and the page language is set
[R `base.html:2`].

| # | Defect | Where | WCAG | Fix | Size |
| --- | --- | --- | --- | --- | --- |
| A11Y-1 | Input, select and text-area borders are `--line`, 1.37:1 against the card (1.36:1 dark): the edge of a field is nearly invisible | `console.css:48` | 1.4.11 Non-text contrast (3:1) | A separate `--field-line` token at ≥ 3:1 (e.g. the muted colour) for form controls only; leave table rules as they are | S |
| A11Y-2 | In dark mode the amber row (`tr.amber`) mixes 40 % yellow into the dark background: muted text falls to 2.95:1 and links to 2.64:1 | `console.css:319` | 1.4.3 Contrast (4.5:1) | Use `--warn-bg` for the row in both schemes, as `table.approval tr.amber` already does (`console.css:293`) | S |
| A11Y-3 | The ten-minute idle lock gives no warning and no way to extend; a half-filled AE form is lost (R, E-M3 saw the loss) | `services/console/auth.py:71` | 2.2.1 Timing adjustable (A) | A warning page or banner one minute before, with "Stay signed in"; keep the form's text (R39) | M |
| A11Y-4 | Field errors are page-level alerts not tied to the field: `aria-invalid` in 2 templates, `aria-describedby` in 9, of 133 [M 2] | e.g. `_data_err.html:3`, `_edc_err.html:3` | 3.3.1 Error identification; 4.1.2 | One macro for a field with its error, used by every form | M |
| A11Y-5 | The phone menu is a hidden checkbox with `aria-label` and a label marked `aria-hidden`; a screen reader hears "Menu, checkbox, not checked", not a button with an expanded state | `base.html:24-25` | 4.1.2 Name, role, value | `<details><summary>` (already used for "More") or `role="button" aria-expanded` with the small script | S |
| A11Y-6 | 97 tables, 36 `caption` or `scope="col"` [M 3]; on a phone the R report found the important column off-screen (R, E-4) | templates | 1.3.1 Info and relationships | `scope="col"` on every header row; cards under 640 px (in hand for the week list) | S |
| A11Y-7 | A page refreshes itself every 5 s while a job runs | `base.html:7` | 2.2.2 / 3.2.5 (AAA); advisory at AA | A "Refresh" button and an `aria-live` status line instead of a reload | S |

Focus order follows the source: skip link, brand, menu, help, ask, search, menu items, account, role switch,
language, sign-out, then the page [R `base.html:13-56`]. On a desktop that puts eleven stops before the content; the
skip link is the remedy and it exists. Target size: small buttons are 28 px high (`console.css:56`), above the 24 px of
2.5.8. Neither keyboard traps nor drag-only actions were found in the templates read [R]. A screen-reader run was
not done (not verified).

---

## 4. Scenarios beyond a pharma drug trial

**What the product already knows about study kinds.** A study's settings hold a type of three values, `trial`,
`registry`, `observational`, and a cohort kind, `enrolled` or `dynamic` [R `services/console/sitestore.py:40-41`].
The SAE rules apply to `trial` and `observational` only [R `services/console/study_setup.py:106`]. A Cohort page
lists "members of the registry or observational study. There is no contact step" [R
`docs/guides/coordinator.en.md`, "Cohort"]. A COHORT run exists (`authz_matrix.yaml`, `command.COHORT`). The seven
built-in site forms are screening log, consent, enrolment, visit, adverse event, deviation, withdrawal [M 4]. The
rule-set manifest has a `kind` (RA-BIO is `kind: nhi`) [R `rulesets/RA-BIO/manifest.yaml:2`].

The phases used below are those of the owner's life cycle. "Today" names the page or module [R]; "Missing" what a
site would need; "Different in kind" what is not a variation of the drug-trial page but a different thing.

### 4a. Investigator-initiated study (IIS)

No sponsor, no CRO; a small team; the IRB is the main counterpart; the PI is also the sponsor (sponsor-investigator).

| Phase | Today | Missing | Different in kind |
| --- | --- | --- | --- |
| Feasibility | Feasibility report; the sponsor copy | The "sponsor copy" wording assumes a sponsor | The feasibility is for the PI's own grant or IRB application |
| Start-up | Protocol in, criteria approved, IRB record, ICF version | An IRB-facing pack: protocol version, ICF version, approval dates | The PI approves his own criteria and is his own sponsor: no second person checks the rule set [O] |
| Finding people | Week list, candidates | – | – |
| Approach, consent | Same as a trial | – | – |
| Enrolment, visits, data | Participants, visits; TrialBox's own data pages | IIS often has **no EDC**: TrialBox's own forms *are* the record. R recommends hiding free CRF entry for a study linked to an EDC (R, G "redundant"); for an IIS without an EDC it must stay | Data management (queries, lock) falls on the site: a "lock this study's data" step that today does not exist |
| Safety | SAE register; "sent to sponsor" | For an IIS the reports go to the IRB and the regulator, not a sponsor; the SAE rules need an "IIS" set | Expedited reporting is the PI's duty as sponsor |
| Monitoring | CRO grant | Usually none, or a hospital's own quality office | A "self-monitoring" checklist instead of a CRO visit |
| Close, archive | Study state; retention years | The IRB's final report | – |
| Opt-out | Same | – | – |

**Verdict:** a variant of the trial. One study-type value, `iis`, that renames "sponsor" to "IRB / regulator" in the
SAE and close steps, keeps the data pages on, and offers a data lock. [O]

### 4b. Biomarker or registry study (samples, a biobank link, consent for future use, no intervention)

| Phase | Today | Missing | Different in kind |
| --- | --- | --- | --- |
| Feasibility | Yes; counts by criteria | Counts of patients with a stored sample of the right kind (needs a sample feed) | – |
| Start-up | Study type `registry`; no SAE rules (`study_setup.py:106`) | The SAE rules are hidden, but the delegation-log chores and the conduct pages are not (R, F-2) | – |
| Finding people | COHORT run; Cohort page; `dynamic` cohort kind | – | The cohort may be open-ended (dynamic): no "enrolment closes" |
| Approach, consent | The trial's consent form (16 fields) [R `forms.csv:11-26`] | **Tiered consent**: samples yes/no, genetic testing yes/no, future research yes/no, re-contact yes/no, return of results yes/no. None exists | Consent is per *use*, not per study, and it must follow each sample |
| Enrolment | Enrolment form | A sample log per participant: kind, date, aliquots, location, the consent scope that governs it | The unit of record is the sample, not the visit |
| Visits and data | Visits | Collection events, not CRF visits | – |
| Safety | None, rightly | – | A sampling-procedure incident is not an AE of a product |
| Monitoring | – | – | – |
| Close, archive | Study state | The biobank transfer; the sample retention decision | Samples outlive the study |
| Opt-out, withdrawal | Withdrawal with "data may be used" (unread; R, C-1) | Withdrawal per scope: "destroy my samples", "keep but no new use"; a receipt | Withdrawal must reach the lab; Taiwan's biobank law governs (人體生物資料庫管理條例; not verified here) |

**Verdict:** different in kind at consent, enrolment and withdrawal. A study-type value `biomarker` (or
`registry` with samples on), a tiered-consent form, a sample log form, and an export the lab or biobank reads. No new
role at first. [O]

### 4c. Observational or retrospective research (cohort definition, no approach, waiver of consent, extraction)

| Phase | Today | Missing | Different in kind |
| --- | --- | --- | --- |
| Feasibility | Counts | – | Feasibility *is* most of the study |
| Start-up | Type `observational`; the IRB record | A **waiver of consent** recorded with the IRB's decision and its legal basis; the Human Subjects Research Act lets the authority announce categories exempt from consent (Art. 12(2)) and from review (Art. 5(1)) [S https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0020176] | The legal basis replaces the consent form |
| Finding people | COHORT run, Cohort page, "no contact step" | The cohort definition as an approved, versioned rule set (it already is: rule sets are versioned and approved) | – |
| Approach, consent | None, correctly | – | No person is approached; the patient never meets the study |
| Enrolment | – | – | Membership is computed, not recorded |
| Visits and data | – | **The extraction**: which variables, for which cohort version, de-identified how, for whom, with what audit | The deliverable is a dataset; this is the data steward's work, not the coordinator's |
| Safety | SAE rules apply to `observational` (`study_setup.py:106`) | For a *retrospective* study there is no safety reporting; the rule set should not be offered | A prospective observational study does report; split the type |
| Monitoring | – | – | – |
| Close, archive | – | The extraction log and the dataset's hash archived | – |
| Opt-out | The register removes the patient from lists | An opted-out patient must leave the *extraction*, and a later extraction must say how many left | The opt-out (research use of NHI or hospital data) is the only patient voice in this study |

**Verdict:** different in kind: no participant at all. Split `observational` into `prospective` and
`retrospective`; give the retrospective type an "Extraction" step owned by the steward (approve, run, export with
an "about" block and a ledger row, R30), and no conduct pages. [O]

### 4d. Medical device study

| Phase | Today | Missing | Different in kind |
| --- | --- | --- | --- |
| Feasibility, start-up, finding, consent | As a trial | Device-specific criteria (implant, MRI conditional, prior device) are ordinary criteria | – |
| Enrolment | As a trial | – | – |
| Visits and data | Visits | Procedure date and operator; device identifiers (UDI) per participant | The procedure is the intervention, often on day 0 |
| Safety | AE form with seriousness, relatedness, CTCAE grade [R `forms.csv` `ae_*`] | **Device deficiency** (a malfunction, use error or inadequate labelling, with or without harm), device-relatedness and procedure-relatedness, the "unanticipated serious adverse device effect" category of ISO 14155 (not verified against the 2020 text) | Safety is about the device as well as the patient: a deficiency without any AE is still reportable |
| Monitoring | As a trial | – | – |
| Device accountability | Nothing (study drug is outside TrialBox too, R A-M6) | Receipt, implant, return, explant per device | Accountability is per serial number and follows the patient's body |
| Close, archive | As a trial | Long-term follow-up for implants | Follow-up may outlive the study's normal close |

**Verdict:** a variant of the trial with a different safety form. A study-type value `device` that swaps the AE
form for an AE-plus-device-deficiency form and adds a UDI field to enrolment. Device accountability stays outside
TrialBox with a signpost, as drug accountability does. [O]

### 4e. Patient finding and management for reimbursement (biologics under Taiwan's NHI)

**What NHI asks, in outline.** For RA biologics the NHI uses a DAS28 assessment form (附表十三) and an application
form for biologics (附表十五), for adults with ICD-10-CM M05 or M06, uploaded through the NHI VPN's prior-review
screen [S https://www.nhi.gov.tw/ch/dl-42660-1a2784010a7149b2abddf9880f94171a-1.pdf, opened and read as text]. A
published amendment for abatacept shows the shape of such a rule: prior TNF failure defined by DAS28 (a fall of
≥ 1.2 or a score < 3.2), a prescriber restriction (internist with a rheumatology or immunology certificate), prior
review before use, an assessment at 24 weeks and then every 12 weeks to continue, photographs with each
application, and listed stopping conditions [S https://www.nhi.gov.tw/ch/dl-8064-c89da6ddd399412194c00ef9952812e6-1.pdf;
a draft of the time, "自○○○年○○月1日生效"; whether this is the current text is not verified]. Prior authorisation by
FHIR follows the NHI's TWPAS guide, now version 1.3.0 (STU, "Active as of 2026-10-28"), covering cancer drugs and
immunologic agents [S https://nhicore.nhi.gov.tw/pas/].

**What TrialBox already has** (all in the orchestrator; none in the console):

| Piece | Where | What it does |
| --- | --- | --- |
| NAV run | `services/orchestrator/scenarios/nav.py:1-11` | Weekly or by mail; patients with an appointment in the next 14 days in the named departments: **likely eligible** (inclusions pass, no exclusion, no active approval, no application in 90 days), **renewal due** (approval ending within the lead days), **documentation gaps** with suggested orders, **maybe ineligible** (a renewal criterion fails). An application draft (docx, with `[待補]` markers) per row. Lists mailed encrypted |
| TWPAS bundle | `services/orchestrator/reports/twpas_bundle.py:1-5` | A FHIR prior-authorisation Bundle per IG 1.2.5: Claim, Patient, Practitioner, Coverage, the MedicationRequest, supporting Observations; PHI resolved in the box |
| SUBMIT | `services/orchestrator/scenarios/submit.py:1-15` | A physician replies by mail to send one bundle to the NHI; "never automatic; the only path on which PHI leaves the box"; a dry run by default |
| Rule sets | `rulesets/RA-BIO/manifest.yaml` (`kind: nhi`; INC, EXC, REN renewal and DOC documentation criteria; departments RHEU; renewal lead 60 days), `rulesets/ONC-OSI/` | Synthetic examples; approved by the owner in a project chat [R `manifest.yaml:2,34-40`] |
| Settings | `deploy/settings.example.yaml:32,48` | NAV scheduled Monday 03:30; TWPAS enabled, dry run on |
| Specification | `spec/v4/10b_modules_m6_m11_workflows.md:393-445` (M10) | Carries NAV over; adds coverage analysis at feasibility, budget draft, billing guard |

**Walk through the life cycle.**

| Phase (reimbursement equivalent) | Today | Missing | Different in kind |
| --- | --- | --- | --- |
| Feasibility → "how many of our patients qualify" | FEAS works on an `nhi` rule set [O: not run here] | – | A department's planning number, not a study's |
| Start-up → the rule loaded | Rule set compiled and approved | **Editions**: NHI rules change by announcement; FR-M10-5 asks for versioned editions with effective dates [R `spec/v4/10b_modules_m6_m11_workflows.md:432`]; not built | The "protocol" is a public regulation with amendments, owned by nobody at the site |
| Finding people → "who qualifies" | NAV `likely_eligible` | A **console page** (a list with evidence, like the week list) | The list goes to the treating physician for a *treatment* decision |
| Approach, consent → none | – | – | **No research consent.** The patient is in ordinary care; the legal basis is care and the NHI's own rules |
| Enrolment → application and approval | Draft docx; TWPAS bundle; SUBMIT by mail | Tracking the approval: submitted, approved (with its period), rejected (with reason), appealed; today the ClaimResponse is stored and shown nowhere | The approval is a *payer's* decision with a validity period |
| Visits and data → continuation | NAV `renewal_due`, `maybe_ineligible`; REN criteria | A follow-up schedule per approved patient: DAS28 at 24 weeks, then every 12 (in the abatacept example); the assessment form pre-filled from the record; photographs | Response criteria at fixed intervals decide whether the drug continues |
| Safety → stopping rules | EXC criteria; `maybe_ineligible` | A stopping-rule alert (serious infection, pregnancy, no response) to the treating physician | Pharmacovigilance is the ordinary hospital route, not a study's SAE |
| Monitoring → NHI audit | – | A per-patient file of what was sent and when (the bundle's hash is audited) | The auditor is the payer |
| Close, archive → patient stops the drug | – | – | No close; patients enter and leave continuously |
| Opt-out | FR-M10-8 asks NHI-derived signals to honour the `nhi_secondary_use` scope [R `10b...md:433`] | Not built | The research opt-out does **not** apply to the patient's own care; the list must not drop a patient because they opted out of research [O] |

**Who the users are.** The treating department (rheumatology), a case manager (often a nurse, the "list_to" of
RA-BIO's routing), the pharmacy (checks an approval before dispensing), and the hospital's NHI application office
(申報). None of them is a trial role; mapping them onto "coordinator" and "investigator" would give them research
rights (`list.mark`, `criteria.approve`, `task.*`) they should not have and miss the rights they need. [O]

**How it differs from a trial, plainly.**

- **Purpose.** A trial list asks "may this patient join a study?"; the investigator decides and the patient
  consents. A reimbursement list asks "does this patient qualify for a paid treatment?"; the answer feeds a
  treatment decision.
- **The intended-use statement.** The normative statement: TrialBox "is not intended to diagnose, treat, mitigate or
  prevent disease or to inform an individual patient's clinical management" [R
  `spec/v4/01_constraints_product_experience.md:293-295`]. The regulatory position: TrialBox "does not recommend
  treatment" and is "not a medical device" in Japan or Taiwan, a position that "depends on the intended use"
  [R `docs/plan/design/16-regulatory-position.md:24,28`]. A list naming patients likely eligible for a biologic, with
  a pre-filled application, **informs an individual patient's clinical management**. It contradicts the statement
  as written. The specification itself requires a written intended-use analysis before shipping "anything that would
  … recommend treatment" [R `spec/v4/01_constraints_product_experience.md:297-304`]; the regulatory position does not
  mention NAV or TWPAS at all [M 5].
- **The regulatory consequence** [O; not legal advice]. Software that identifies patients who meet the criteria for a
  specific therapy may be read as clinical decision support. Whether it is a medical device in Taiwan (醫療器材管理法)
  or Japan (the program medical device guideline) depends on how the output is framed: "these patients meet the
  payer's administrative documentation rules, for review by their physician" is an administrative aid; "these
  patients should start a biologic" is a treatment recommendation. The first framing is defensible only if the
  screen and the mail never rank, never suggest a drug, and say so.
- **PHI leaves the box.** SUBMIT is the only path on which PHI leaves (submit.py:2). Every other part of TrialBox
  is designed so it never does.

**What it reuses.** The criteria compiler and rule sets (`kind: nhi`), the candidate list with evidence, the mark
and the hand-over as a task, the follow-up schedule (visits), the morning mails, the audit trail, the opt-out
machinery (with the opposite default), the terminology tables (NHI drug codes; B-1 found only 24 rows [B-1, M 5]).

**Recommendation** [O]: put the decision to the owner (section 5, decision card J-D1) with three choices:

1. **Leave NAV, TWPAS and SUBMIT out of release 1.0** and say so in the release record; keep the code behind a
   setting that is off and cannot be turned on in PRODUCTION. Cheapest, and the 1.0 intended use stays true.
2. **A separate module, "Reimbursement", with its own intended-use statement, its own roles (case manager,
   pharmacist, NHI office), its own regulatory analysis and validation, sold and switched on separately.** The
   console page, the approval tracking and the follow-up schedule are then L items.
3. **Widen TrialBox's intended use** to include "administrative support for reimbursement documentation". This
   changes every label, footer and the regulatory position in three languages, and needs counsel.

This page recommends 1 for release 1.0 and 2 afterwards. The TWPAS version the box pins (1.2.5) is already behind the
published 1.3.0 [R `deploy/settings.example.yaml:29`; S nhicore], which is one more reason not to ship it unattended.

### Common core and switches

| Part | IIS | Biomarker / registry | Observational (retro) | Device | Reimbursement | Core or specific? | Switch |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Criteria as rules over the record (compiler, rule sets, approval, versions) | ● | ● | ● | ● | ● | **Core** | always on |
| A list of people with the evidence per criterion | ● | ● | ● (cohort) | ● | ● | **Core** | always on |
| A person decides; the decision and its reason are recorded | ● | ● | ● (cohort approval) | ● | ● | **Core** | always on |
| Tasks and hand-overs between people | ● | ● | – | ● | ● | **Core** | always on |
| A schedule of follow-ups | ● | ● (collections) | – | ● | ● (renewals) | **Core** | always on |
| Audit trail, opt-out register, roles | ● | ● | ● | ● | ● (opt-out inverted) | **Core** | always on |
| Feasibility counts | ● | ● | ● | ● | ● | Core | module: Feasibility |
| Contact and approach | ● | ● | – | ● | – (care, not research) | Specific | **study type** |
| Research consent (single) | ● | – | – | ● | – | Specific | **study type** |
| Tiered consent and samples | – | ● | – | – | – | Specific | **study type** (`biomarker`) |
| Waiver of consent with its legal basis | – | (sometimes) | ● | – | – | Specific | **study type** |
| SAE rules (drug) | ● | – | (prospective only) | – | – | Specific | **study type** |
| Device deficiency, UDI | – | – | – | ● | – | Specific | **study type** (`device`) |
| Extraction (dataset, ledger) | – | ● | ● | – | – | Specific | **study type** |
| EDC link | (rare) | – | – | ● | – | Specific | **module** (EDC) and per study |
| Monitoring (CRO) | – | – | – | ● | – | Specific | **module** (Monitoring) |
| Payer application, approval tracking, renewals | – | – | – | – | ● | Specific | **module** (Reimbursement), off in 1.0 |

**The rule** [O]: a **module** is what a site has bought and staffed (it changes menus for everyone, roles and
containers); a **study type** is how one study runs (it changes the steps, forms and checklists of that study only).
Today the type has three values; it should have six (`trial`, `iis`, `device`, `biomarker`, `observational_prospective`,
`observational_retrospective`), each with its checklist, its step strip and its forms. Reimbursement is not a study
type: it has no study, no consent and no close; it is a module with its own intended use.

---

## 5. Cards for plan 9, and decisions

Sizes: S (a day or less), M (a few days), L (a week or more); estimates. Lane guesses: C2a (the journey), C2b (trust
and operations), E (EDC, terminology), D (installer), A2 (screening), R (review), Int (integrator), Owner. "Waits
for" names a card or a decision.

### Decisions for the owner

| # | Decision | Recommendation | Why now |
| --- | --- | --- | --- |
| J-D1 | NAV, TWPAS and SUBMIT in release 1.0? | **Out of 1.0**, off and unsettable in PRODUCTION; a separate Reimbursement module later with its own intended use | It contradicts the 1.0 intended-use statement; the TWPAS version is behind |
| J-D2 | Combinations of duties a hospital may give one person | coordinator + steward **no**; admin + privacy **no**; admin + any patient role **no** (D-280); one person, one account, enforced | Hospitals will ask at implementation |
| J-D3 | Phone: installable web app without a service worker; mail as the notification channel; no native or wrapped app | **Yes** | Confirms plan 8 "Out" and closes the question |
| J-D4 | Study types: six values, each with its own steps and forms | **Yes**, built after modules (in hand) | The owner asked for biomarker and research studies |

### Cards

| # | Card | Section | Size | Lane | Waits for |
| --- | --- | --- | --- | --- | --- |
| J-1 | "Your role in each study" on home and account (PI here, sub-I there, with the ticked tasks) | 1.3 | S | C2a | – |
| J-2 | Bind each account to one staff-register person; refuse a D-719 confirmation between two accounts of one person; list a person's accounts on the steward page | 1.3 | M | C2b | J-D2 |
| J-3 | PI cover in one step: a covering entry with dates, a study banner, mails N1 to the covering PI for those dates, a task "notify the IRB" | 1.3 | M | C2a | – |
| J-4 | Warning two weeks before a delegation entry ends; an unacknowledged SAE after N days also goes to the sub-investigators and the coordinator | 1.3 | S | C2a | – |
| J-5 | Optional task owner and "lead coordinator" per study; "reassign X's open tasks to Y" on departure | 1.3 | M | C2a | One status (in hand) |
| J-6 | OIDC refusal page names the two clashing groups | 1.3 | S | C2b | – |
| J-7 | The viewer shown as "research office"; Japanese role words 研究責任者／研究分担者 for non-治験 study types | 1.1 | S | C2a | J-12 for the type |
| J-8 | One immediate short mail when an SAE is saved (pseudonym and link only), not only the next N1 | 2.2 | S | C2a | – |
| J-9 | One paragraph per role guide: install the console as an app (Edge, Safari, iOS, Android); the hospital CA must be trusted; FSLogix note | 2.3 | S | C2a, W | Manifest (in hand) |
| J-10 | Passkeys (WebAuthn platform authenticator) as the re-authentication at signature, beside the password; a Part 11 note | 2.2 | M | C2b | – |
| J-11 | A written rule: no service worker, no offline cache of clinical pages, no consent scans, no web push through outside push services; a test that fails if a service worker is registered | 2.2 | S | C2a | J-D3 |
| J-12 | Study type with six values; each with its step strip, checklist and forms; the SAE rules offered only to the types that report | 4 | L | C2a | Modules and home by phase (in hand) |
| J-13 | IIS: "IRB / regulator" in place of "sponsor" in SAE and close; a data lock for a study without an EDC; an IRB pack export | 4a | M | C2a | J-12 |
| J-14 | Tiered consent form (samples, genetic, future use, re-contact, results) | 4b | M | C2a, E | J-12 |
| J-15 | Sample log per participant with the consent scope; export for the lab or biobank; withdrawal per scope | 4b | L | C2a, E | J-14 |
| J-16 | Waiver of consent recorded with the IRB decision and its legal basis | 4c | S | C2a | J-12 |
| J-17 | Extraction step for retrospective studies: approve, run, export with an "about" block and ledger row; opt-outs counted out | 4c | L | C2b, B2 | J-12; R30 |
| J-18 | Device study: AE plus device deficiency form; UDI on enrolment; signpost for device accountability | 4d | M | C2a | J-12 |
| J-19 | Fence NAV, TWPAS and SUBMIT: a setting off by default, refused on PRODUCTION; the release record says it is out | 4e | S | Int, A2 | J-D1 |
| J-20 | If J-D1 is "a module": the Reimbursement intended-use statement and device analysis in three languages, with counsel | 4e | L | Owner, R | J-D1 |
| J-21 | If a module: a console page for NAV lists with evidence; approval tracking from the ClaimResponse; a renewal schedule; roles for case manager, pharmacist, NHI office | 4e | L | C2a, A2 | J-20 |
| J-22 | If a module: NHI rule editions with effective dates (FR-M10-5); TWPAS moved to the version NHI requires | 4e | M | E | J-20 |
| J-23 | A11Y-1: a field-border token at ≥ 3:1 | 3.3 | S | C2a | – |
| J-24 | A11Y-2: the dark-mode amber row uses `--warn-bg` | 3.3 | S | C2a | – |
| J-25 | A11Y-3: warn one minute before the idle lock, with "Stay signed in"; keep the form's text | 3.3 | M | C2b | – |
| J-26 | A11Y-4: one field macro with error, `aria-invalid` and `aria-describedby`, used by every form | 3.3 | M | C2a | – |
| J-27 | A11Y-5 to 7: the phone menu as `<details>`; `scope="col"` on all tables; a refresh button and live status in place of the meta refresh | 3.3 | S | C2a | – |
| J-28 | Inline definitions of system words from the glossary, on the page, in three languages | 3.2 | S | C2a | One Help (in hand) |
| J-29 | "Your first week" card per role, ticked off then gone; no overlay tours | 3.2 | S | C2a | Home by role (in hand) |
| J-30 | The search field finds a participant by screening number and a patient by pseudonym (roles that may) | 3.2 | M | C2a | One Help (in hand) |
| J-31 | A V13 round with one person per scenario type (IIS, registry, retrospective) holding only the guide | 4 | M | R | J-12 |

**Count:** 31 cards: 14 small, 12 medium, 5 large. Start now with no ruling: J-1, J-4, J-23, J-24.

---

## 6. Measurement log

| n | Command | Result |
| --- | --- | --- |
| 1 | A 30-line Python script (in the scratchpad, not committed) computing WCAG 2 contrast from the tokens of `console.css:3-11`, and the 40 % blend of `console.css:319` | Light: ink/bg 14.6, muted/bg 5.43, accent/card 6.45, line/card 1.37, amber row muted 4.58, accent 5.08. Dark: ink/bg 15.04, muted/bg 8.19, line/card 1.36, amber row muted 2.95, accent 2.64 |
| 2 | `grep -l aria-invalid templates/*.html \| wc -l`; the same for `aria-describedby`; `ls templates \| wc -l`; `wc -l static/*.css`; `grep -n 'title=' templates/*.html \| wc -l` (all under `services/console/`) | 2; 9; 133; 561; 19 |
| 3 | `grep -n '<table' templates/*.html \| wc -l`; `grep -n -E '<caption\|scope="col"' templates/*.html \| wc -l` | 97; 36 |
| 4 | `cut -d, -f2 services/datacore/builtin/forms.csv \| sort \| uniq -c` | 7 forms: screening log 9 fields, consent 16, enrolment 7, visit 6, adverse event 22, deviation 7, withdrawal 5 |
| 5 | `grep -n -i -E "nhi\|reimburs\|NAV\|給付\|insurance" docs/plan/design/16-regulatory-position.md` | no match |

---

## 7. What this document did not verify

- **No page was opened on a running box** for this document; the screens are from the cited screenshots and from
  templates. A screen-reader and keyboard run was not done; the focus order is read from the template's source order.
- **NHI rules:** the current text of 藥品給付規定 section 8 for each RA biologic (initial thresholds, continuation
  interval, tapering) was not found; the abatacept amendment cited is a draft of its time. The "two DAS28 > 5.1"
  initial rule seen in a search summary was not opened. The NHI pre-check service and submission endpoint were not
  examined.
- **NAV and FEAS on an `nhi` rule set were not run**; their behaviour is read from the code's docstrings.
- **Whether the mails N1 follow a covering PI's entry dates** was not traced in code.
- **Mobile regulation:** the mobile and BYOD clauses of Japan's guideline 第7.0版 were not read (only its index page);
  the US proposed Security Rule of January 2025 could not be opened (HHS and the Federal Register refused the fetch);
  Taiwan has no article on devices or remote access in the EMR regulation (read), but hospital-level rules were not
  searched.
- **Store and MDM:** managed Google Play's handling of web apps was not confirmed (the page did not say); Apple's
  Developer Enterprise Program was not examined.
- **ISO 14155:2020** device-deficiency definitions are from memory, not from the standard's text.
- **Taiwan's Human Biobank Management Act** (人體生物資料庫管理條例) was named, not read.
- **The device-status consequence for reimbursement** (section 4e) is an opinion, not legal advice; counsel must read it.
- The sizes of the cards are estimates.
