# D-1232 Consent by a representative (代諾者) and the participant's assent (アセント) on the consent record (10C-19)

- **Task:** plan 10, Track C, card 10C-19 (review 11, JP-20), lane J. · **Date:** 2026-11-19
- **Decision:**
  - **One setting, switched on by the Japan profile.** `TB_CONSENT_PROXY` is `on` or `off`; unset, it is on where
    the site's zone names Japan (`TB_TZ` Asia/Tokyo, as `tb_common.derived.country_of` reads it) and off elsewhere.
    Any site may set it. Off, every page and export is as before the card (proved byte for byte against master in
    the card's pull request): the code reads the setting where it adds something and adds nothing when it is off.
  - **On the consent form** (the built-in `tb_consent`, six items at the end of the form; their words in
    `datacore/builtin/forms.csv`): the age at consent in whole years; the representative's relation as a code
    (parent 親権者, guardian 後見人, spouse, adult child, other with one word), shown when the form's existing
    "consent given by a legal representative" is yes; the assent obtained or not, with why not as a code (too young to
    understand, lacks the capacity, declined) and the day of assent. The coded relation takes the place of the free
    text relation while the setting is on. **Never the representative's name, address or contact**: the form says
    so. Who recorded each answer is the data core's record of the save.
  - **Warnings, never refusals**, on the consent in force (the last recorded), per study: the age of majority
    (default 18, Japan's since 2022) and the assent ages (default 7 to the year before majority) are set on the study's
    set-up page by whoever may set its contact rule (audited `life.consent_ages`). Under the age of majority with no
    representative: `no_representative`; in the assent ages with no assent entry: `no_assent`. Each warning names
    what is missing and links to the consent form (to the record for a reader who may not enter).
  - **A declined assent** is an alert (the page's error style) and the consent form is then not taken as consent to
    proceed: the participant stays before "consented" (a later enrolment or visit holds it, as a missing consent
    form does), and only a person's step "Consent given" with the reason in its note moves it on; without a note the
    step is refused (`life.refused`, `assent_reason`); the step is audited (`life.step`) and the note kept in the
    trail. This follows how a declined consent is treated today: never implied, a person's recorded step.
  - **Age.** The participant record is de-identified and holds no date of birth, so the age is whole years: the age
    at consent on the form, else the age at enrolment (on or after the consent day, so never younger). No age, no age
    warning, and the record says the age is not recorded.
  - **Where it shows:** the participant's consent record, the participants list and the screening log (a pill per
    warning, from the one computation, `Lifecycle.consent_record`), and the screening log's XLSX, five columns at the
    end (`consent_given_by`, `representative_relation`, `assent`, `assent_reason`, `consent_warnings`; codes in the
    machine sheet, words in the sheet for people). The data-core exports (REDCap CSV, ODM, CDISC) carry the six items
    as fields of the consent form, at its end. The sponsor's layout names its own columns and is unchanged.
  - **Who:** whoever records and reads the consent form today records and reads the new items, by the same routes;
    no role reads more.
- **Not here:** a date of birth (the record holds none); per-site lists of relations (the codes are the review's);
  REDCap: a site's REDCap project must take the six fields (its data dictionary uploaded again) before it accepts an
  export made with the setting on.
- **Held by:** `tests/console/test_consent_by_a_representative_and_assent.py`.
