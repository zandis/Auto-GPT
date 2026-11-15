# D-729 Every RUNBOOK page names its reader; IT gets one page; the other install forms are one part

- **Task:** T-735a, the documents part of T-735 ("Documents for the owner"; plan v6.1 addendum, OD-13), in lane D's
  queue (`docs/plan/37-remaining-work-split.md`)
- **PR:** this branch (`agent/T-735a-every-page-names-its-reader`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** D-139 and D-352 (the RUNBOOK and its section files), D-390 (the team's pages in DEVELOPING),
  D-611 (the owner's pages for the Windows box)

## Context

T-735's acceptance is "every page names its reader; an owner can follow the set-up page in the rehearsal". The
RUNBOOK opened with "For the site's IT", and its section table had one audience for the owner and IT alike
(`site`). No page of `docs/runbook/` said who it was for. IT had no page of its own (the network sheet is a long
generated port table), and the procedures for the other install forms (a Spark by hand, a proof of concept, one RTX
5090, a hospital platform) stood among the owner's.

## Decision

1. Each page of `docs/runbook/` has a `**Reader:**` line under its title naming one or more of: the box owner,
   hospital IT, the data steward, the trial team, Aimedics, the people who build TrialBox.
   `tools.doclint.reader_problems` fails a page without one or with no known reader (part of `make doclint`).
2. The RUNBOOK's opening says so and points to the owner's pages (`docs/handover/windows-owner.*.md`) and IT's one
   page. The section table's Audience column says `owner`, `IT`, `steward`, `Aimedics` or `team`, as the page does;
   `site` is gone.
3. **Other install forms** is one part in the RUNBOOK's opening: §8, §9, §10, §17 and §26. The sections keep their
   numbers (D-352: a number is never moved), so links do not break.
4. `docs/handover/it-one-page.{en,ja,zh-TW}.md`: the address (a fixed address and a DNS name, `TB_TLS_HOSTNAME`,
   the certificate), the data connection (a read-only export folder, a backup share or outside disk, the optional
   mail relay and domain controller) and the firewall line (in: TCP 443 from the clinic PCs; out: nothing, or
   `clinicaltrials.gov:443` when the hospital chose live; the time server). Its facts are the network sheet's.

## Not covered

- The owner following the set-up page in the rehearsal: proven at P-0 (D-611), not here.
- The handover pages' reader lines (the generated network sheet, the desktop-use pages) are not checked by doclint.
- The ja and zh-TW one-pagers are written here, not yet read by a native reader (T-317's review).
