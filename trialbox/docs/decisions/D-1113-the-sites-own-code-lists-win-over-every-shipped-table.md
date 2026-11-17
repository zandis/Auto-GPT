# D-1113 The site's own code lists win over every shipped or loaded table

- **Task:** lane H, card H-5 (TERM-2: the install-time code-system loader and its manifest), on the owner's rulings
  D-1028 (code systems loaded at install; the site's own lists are the primary source) and D-1029
- **PR:** this branch (`claude/lane-h-5-term2`)
- **Date:** 2026-11-17
- **Status:** proposed
- **Builds on:** D-858 (TERM-1: the loader, its manifest and its refusal), D-1028 point 2, D-172 (curated synonyms)

## Context

D-1028 point 2 makes the site's own code lists the primary source and keeps them out of the repository. Lane E's
question 3 on #639 asked whether the hospital's own ICD-to-local list may serve as a synonym source at install. TERM-1
built the loader (`tools/terminology_install.py`), the manifest and the refusal, but no command for a site's lists.

## Decision

1. **A site list loads like every other table.** `python -m tools.terminology_install site-list <csv or tsv> --name
   <name> [--system <system>]` writes the table `site_<name>` into `TB_TERMINOLOGY_DIR`, with its line in
   `manifest.json` (source and sha256, version, licence note "the site's own list", rows, when loaded). The format is
   generic: `local_code` and/or `local_name`, `code`, `system` (or one `--system` for the whole file), and an
   optional `display`, in UTF-8 or Big5. The systems are the mapper's: `icd10cm`, `icd10pcs`, `icd10_who`, `loinc`,
   `atc`, `nhi_drug`, `nhi_order`, `department`. A row the loader cannot place refuses the whole file.
2. **Step 0 of `Terminology.map`.** Before every other step, a concept's name that a site list names (`local_name`,
   as written or as ICD-10-CM's lists are matched), for a system of the concept's domain, resolves through that list.
   The method is `site`, no review: the list is the site's own. An ICD-10-CM category in a site list stands for its
   family, as in TERM-1. When two lists name the same name, the first by its name keeps it.
3. **Local codes are kept.** A row's local code and its standard code are indexed (`Terminology.site_codes`). The
   name step does not use them. They are there for the site mapping, which is lane E's and is not changed here.
4. **Nothing changes without a list.** With no `site_*` table loaded, `map` answers exactly as before.

## Not here

The `site` method is not one the site set-up's automatic proposals accept (`services/sitesetup/mapping.py` takes
`exact` and `synonym` only). That set-up is lane E's, and a site name it does not take stays for a person.
