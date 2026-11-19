# D-1232 Consent by a representative (代諾者) and the participant's assent (アセント) on the consent record (10C-19)

- **Task:** plan 10, Track C, card 10C-19 (review 11, JP-20), lane J. · **Date:** 2026-11-19
- **Decision:**
  - **One setting, switched on by the Japan profile.** `TB_CONSENT_PROXY=on` turns it on; anything else, unset
    included, is off. The Japan profile is the site's country (card 10K-1, `tb_common.site_country`: the country's
    `consent_proxy`): the box's plan writes `TB_CONSENT_PROXY=on` for a Japanese site. It is never inferred from the
    time zone, so an installed box keeps today's behaviour until someone sets it. Any site may set it. Off, every page
    and export is as before the card (proved byte for byte against master in the card's pull request).
  - **On the consent form** (the built-in `tb_consent`, five items at the end of the form; their words in
    `datacore/builtin/forms.csv`): the age at consent in whole years; the representative's relation as a code only
    (parent 親権者, guardian 後見人, spouse, adult child, other: no free text), shown when the form's existing
    "consent given by a legal representative" is yes; the assent obtained or not, with why not as a code (too young to
    understand, lacks the capacity, declined) and the day of assent. **Never the representative's name, address or
    contact**: no item can hold one, and the form says so. The form's earlier free-text relation stays on the form and
    in the exports, read only and never required: what was recorded is not hidden, and nothing new is written there.
    Who recorded each answer is the data core's record of the save.
  - **Warnings, never refusals**, on the consent in force (the last recorded), per study: the age of majority
    (default 18, Japan's since 2022) and the assent ages (default 7 to the year before majority) are set on the study's
    set-up page by whoever may set its contact rule (audited `life.consent_ages`). Under the age of majority with no
    representative: `no_representative`; in the assent ages with no assent entry: `no_assent`; no age at consent:
    `no_age` (never guessed from a later age). Each warning names what is missing and links to the consent form (to
    the record for a reader who may not enter). The ages are whole numbers: the age of majority 16 to 21, the assent
    ages from 0 and below it; they are not saved while the setting is off.
  - **A declined assent holds the participant.** A decline is any declined-assent answer ever saved on the
    participant, read from the change history: on any consent event, dated or undated, later corrected or blanked.
    From the moment it is saved the participant is held: no form and no screening-log row moves them to
    "consented" or any later step. **Typed dates play no part in lifting the hold**; the order is the store's own
    (the history's and the steps' ids, never a clock and never a consent date). Only two things lift it:
    - **the reasoned step** taken after the decline was saved: a person's step to consented, enrolled or later,
      with a reason code (the ethics committee decided, the investigator's judgement in the participant's interest,
      the participant gave assent later on paper, other) and a note of at least 10 visible characters (format and
      invisible characters and white space do not count: `tb_common.visible_text`, which break-glass now uses too,
      unchanged for a real note). It records which decline it answers (`assent_proceed`), is audited apart
      (`life.assent_proceed`: record, step, code; the note stays in the trail, not the audit event), and counts
      only while it stands: an undo takes it back and the hold returns. A decline saved after it holds again.
      Without the code and the note the step is refused (`life.refused`, `assent_reason` or `assent_note`);
    - **a new consent version with the assent obtained**: one that did not exist when the decline was saved (its
      first save comes later in the history), on a consent event only (the first consent or a re-consent `rcN`,
      never a visit or another event). A correction of a version that existed then lifts nothing, whatever it
      changes: the answer, its reason code or a date (the simpler choice: no separate correction route).
    It holds whatever the setting: switching it off never releases a recorded decline (the alert is shown only
    with the setting on; the step still needs the code and the note). This follows how a declined consent is
    treated today: never implied, a person's recorded step. A REDCap read-back can write the screening-log row
    "consented" (the site's REDCap says so); the participant record is still held. Data entry and export go on
    while held, as they do on master for a missing consent.
  - **The earlier free-text relation takes no new value** while the setting is on, on every path: the console's
    form (read only), the orchestrator's form save and data entry and a sheet import (refused), a REDCap source
    mapping (refused) and its sync (skipped), a conflict kept as the source's (refused), and the last door every
    writer goes through (`DataCore.write`). A value saved before stays and is exported. Off, nothing changes.
  - **A missing assent where one is expected warns, never blocks** (intended; the owner confirms): a participant of
    10 with no assent entry can reach "enrolled" with the `no_assent` warning shown.
  - **Age.** The participant record is de-identified and holds no date of birth, so the age is the age at consent on
    the form, in whole years; the form says so. A participant who comes of age during the study is not prompted for a
    consent of their own (a known gap): the rules read the consent in force, so recording that re-consent clears the
    warnings.
  - **Where it shows:** the participant's consent record, the participants list and the screening log (a pill per
    warning, from the one computation, `Lifecycle.consent_record`), and the screening log's XLSX, five columns at the
    end (`consent_given_by`, `representative_relation`, `assent`, `assent_reason`, `consent_warnings`; codes in the
    machine sheet, words in the sheet for people). The data-core exports (REDCap CSV, XLSX, ODM, CDISC) carry the five
    items after every other column. The sponsor's layout names its own columns and is unchanged.
  - **Who:** whoever records and reads the consent form today records and reads the new items, by the same routes;
    no role reads more. The study's ages: exactly who may set its contact rule (two new routes, the page action
    `POST /studies/{rs}/setup/consent-ages` and its `/api/v1` twin, with the rows of `setup/contact`).
- **Not here:** a date of birth (the record holds none); per-site lists of relations (the codes are the review's);
  REDCap: a site's REDCap project must take the five fields (its data dictionary uploaded again) before it accepts an
  export made with the setting on.
- **Held by:** `tests/console/test_consent_by_a_representative_and_assent.py`.
