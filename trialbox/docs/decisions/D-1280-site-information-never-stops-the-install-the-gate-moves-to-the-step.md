# D-1280 Missing or unusable site information never stops the install; the gate moves to the step (U-5)

- **Task:** lane U, card U-5, part 2 (U5-2b). The owner's ruling, relayed by the integrator on #639: card U-5
  (7105516148), widened to PRODUCTION (7105617639), the cut (after 7105989411), the choices on #1417, and the ruling
  on U5-2b (after 7108493299) · **Date:** 2026-11-23
- **Status:** reserved for U5-2b (the integrator flips the row when merged)
- **Supersedes in part:**
  - D-274: the PRODUCTION refusal of `backup-install` without an alert route.
  - D-1390 (10K-4): the PRODUCTION install and first-run page that do not finish without a backup off the box and an
    anchor of their own.
  - D-1365 (10K-21): the PRODUCTION first-run page and wizard that refuse a silent chart-number rule and an unnamed
    health-page person.

  Each of those refusals stays, at the step that needs the item.
- **Builds on:**
  - D-1091 (the five stops on a PoC box);
  - `docs/plan/design/install-first-information-after.md` (#1408);
  - `docs/plan/design/install-questions-cut.md` (#1417).

## Decision

1. **The install never stops for site information,** on a PoC box or a PRODUCTION box, whether the information is
   missing or given but not usable. It asks four things: the language, the time zone, the first administrator, and
   the key passphrase only without a TPM. It installs everything. What is still needed goes on one page,
   "Information still needed".
2. **The stops that stay at install are the security ones:**
   - the bundle's signature or hashes;
   - a machine that cannot run it;
   - root;
   - a PoC box that would load real data or become PRODUCTION;
   - a link in the audit anchor's path;
   - a secret, key or folder that others can read or write.
3. **One list.** The site items, the steps each is needed before, and their words in en, ja and zh-TW are
   `libs/tb_common/site_needs.py` (U5-1). Nothing else holds such a list.
4. **Four states.** An item is:
   - **missing**;
   - **unusable**: given, but the step's own check cannot use it, with the reason;
   - **stand-in**: the box put a value in its place;
   - **given**.
5. **Stand-ins.** The keys of the values the box put in place are kept in `deploy/site/needs/stand-ins.json`: keys
   only, mode 0600, never followed through a link (U5-2a). The installer and the page's apply step write it. `doctor`
   and the page read it. The nightly backup's host part carries it. Its folder holds nothing else: the console,
   orchestrator, adapter and mail gateway mount it read-only at `/run/tb-needs`, so a rewrite is seen without a
   restart (the integrator's go on #639). It is not under `/run/trialbox`, which the key's read-only mount already
   holds. Written as root, the file is given to the services' uid, 10001, so mode 0600 still lets them read it.
   - The trial office's mailbox stands in as the first administrator's mail.
   - The hospital's name stands in as a marked name.
   - The chart-number rule stands in as the form read from the first records, until it is confirmed.
   - The backup alarm stands in as the first administrator on the health page.
6. **The gate.** Every step that needs site information calls `site_needs.gate(step, production=…)` before it runs.
   - **On a PRODUCTION box**, the step is refused while an item it needs is missing, unusable or a stand-in. The
     refusal names each item in the reader's language and points to the page.
   - **On a PoC box** the same items are warnings, written to `deploy/site/poc-stops.jsonl` where the host writes
     (D-1091), and the step goes on with the stand-in.
   - **The steps:** staff use from the clinic PCs, the first night on real data, a study opening for real
     patients, a serious adverse event notice, any mail, and reading request mail.
7. **Each refusal that moves is re-asserted at its gate,** in the same pull request as the move, and its test is
   named there. The integrator ruled the five assertion changes of U5-2b on #639.

## Why

The owner's rule: "install first, then the information". A hospital's IT person installs a box in one sitting; the
answers that only the trial office or the medical records office know come later, and a box that is installed and
running lets them be given on one page. Safety does not change place: a step that would act on real patients without
what it needs is still refused, by name.
