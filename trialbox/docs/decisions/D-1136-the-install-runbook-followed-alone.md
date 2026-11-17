# D-1136 The install runbook, followed alone: what the follower may and may not supply

- **Task:** lane H, card H-22 (the integrator, PR #639, 2026-11-17 08:12 UTC): install from the bundle by the
  runbook alone
- **Date:** 2026-11-17
- **Status:** accepted

## Context

The install runbook of a site's IT on Linux is the RUNBOOK hub's opening (where commands run, and as whom) and
section 1 (`docs/runbook/01-install-a-new-site.md`). `tests/unit/test_runbook_install_commands.py` (T-632) already runs
every command of §1, each on its own, against temporary folders and stand-ins. Nothing yet asked whether a reader who
has only the bundle and those pages, and does only what they say in the order they say it, ends with an installed box.
H-22 asks that, and asks for the time, the number of commands and each place the runbook is wrong or silent.

## Decision

1. **What is followed.** The hub's opening and §1, at the commit the run names. The Windows pages, the box form
   (§16, `box-install.sh`) and the hand-over sheets are other readers' paths and are not read by the follower.
2. **The extraction rule** (`tools/runbook_install.py extract`). A command is an inline code span (it may wrap a line)
   outside a fenced block, or a logical line of a fenced block, whose folded text starts with `sudo`, `python`,
   `deploy/`, `tools/`, `make`, `docker`, `cd`, `TB_`, `--` or `systemctl` and holds a space or ends in `.py` or `.sh`.
   This is T-632's rule; the test holds the two lists equal. Each command keeps its file, line, block and the
   sentence that introduces it. A command that starts `--` is a fragment. The extractor runs nothing.
3. **The install path.** The hub's convention (`/opt/trialbox`, as root); step 1's prerequisites, checked on the
   machine and never installed; the **One command.** paragraph's command; then, in order, each numbered step the one
   command's paragraph does not say the installer does: 4 (the mapping check), 6 (the vendor key), 7 (the first
   ingest and its report). Steps 2, 3, 5 and 8 are the installer's by the runbook's own words; 9 and 10 point to
   other sections and have no command. Every quote that makes a step is held by the test. Every other command of §1
   is listed as not needed by the path, with the runbook's reason.
4. **What the follower may supply.** Only what the runbook tells the reader to bring:
   - the signed bundle, named by its path on the machine (the one command's `trialbox-<version>.tar`);
   - the vendor key "received out of band", placed only where and when the runbook says (step 6);
   - the site's folder of "What the site brings" (`site.yaml` beside `mapping/`), placed in `/opt/trialbox`, the only
     place the one command's relative `--answers site.yaml` names. Its values are the hospital's, so they come from
     the box rehearsal's documented synthetic answers (`tools/rehearse_box/site_answers.yaml` and its mapping); an
     answer the runbook names as required that those answers lack (`sae_office_mailbox`) gets a synthetic value. Each
     supplied value is listed in the record as "left to the reader";
   - the feed folder's content (the hospital's export): the synthetic site A export;
   - an Enter at a question, as a reader at the terminal gives. A question the runbook does not name is a finding;
   - `sudo` is dropped where the follower is already root (the hub's "as root").
5. **What it may not supply.** Anything else: no folder made, no package installed, no environment variable, no step
   reordered, no option added. If the runbook's text does not install the box, the verdict is "the runbook alone does
   not install the box: stopped at <step> because <evidence>". That is a valid, reported outcome.
6. **Lifts.** After the verdict the follower may go on, to find the next place the runbook is silent, only by a lift
   named in the tool (`LIFTS`): the smallest remedy that the stop's own message or another repository page states,
   applied once and recorded; every later result is marked "after lifts". A lift never changes the verdict. A lift of
   kind `machine` says the machine lacks what step 1 names (no TPM in a container); its stop is not a finding. On a
   machine without a GPU the one command's tier stops the installer, as the runbook says; the follower then uses the
   runbook's own words for that machine (`--mode stub`) and records what happened.
7. **Findings are checked, not stamped.** The committed file
   `docs/plan/measurements/runbook-install-2026-11-17/findings.json` lists each finding with the runbook's words, its
   kind (wrong or silent), its severity (stops the install, slows the reader, cosmetic), the step where a run sees it
   and the machines that saw it. The test fails when a finding's quote is no longer in the runbook, when a static
   finding is no longer shown by the text or a new one is, and when the follower's run on a machine shows a finding
   the file does not hold or does not show one the file holds for a step it reached. So a runbook fix makes the test
   fail until the file says the finding is gone, and a new silence makes it fail until the file holds it.
8. **Where it runs.** The unit test runs the follower on a stand-in machine (a folder for `/opt`, a stand-in Docker
   that serves nothing past the host checks, a signed bundle of this checkout's host tree). `make runbook-install`
   runs it beside the box rehearsal on the rehearsal's own clean Ubuntu 24.04 host image with a site bundle made the
   vendor's way and the box images cleared from the Docker host. `--machine vm` runs it on a clean VM as root. The
   record never keeps the administrator's password or enrolment code, nor any value printed after a secret's name.

## Consequences

- The runbook is not corrected here: lane D owns it. The findings go to lane D through the integrator.
- A change to §1 that fixes a finding, or moves a quote the path depends on, fails
  `tests/unit/test_runbook_install_follow.py` until the findings file or the path is updated in the same change.

## Used by

`tools/runbook_install.py`, `tests/unit/test_runbook_install_follow.py`, the `runbook-install` target of the
`Makefile`, `docs/plan/measurements/runbook-install-2026-11-17.md` and its folder.
