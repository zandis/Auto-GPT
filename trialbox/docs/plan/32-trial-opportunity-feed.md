# 32. Trial-opportunity feed: plan addendum to TB-PLAN-06

- **Date:** 2026-11-12
- **Owner request:** 2026-11-12 (project thread "Plan monetizing hospital trial-opportunity data"): add to the plan,
  add cards, build it, a sample page, and later run CGRD against every actively recruiting trial for feasibility.
- **Numbers:** this addendum was drafted as file 31 with cards T-690 to T-695 and decision D-449. Those were taken
  (the scale review's cards T-687 to T-704; D-449 is T-203b's; file 31 is TB-PLAN-06.1). It is file 32, cards T-740 to
  T-745, decision D-467; the next free decision number is taken from `REGISTRY.md` at start.
- **Decision:** D-467 (`docs/decisions/D-467-trial-opportunity-feed.md`)
- **Sample page:** https://claude.ai/artifact/LQw5dNtFWvAC6G8txPic7B (today's recruiting AD and RA trials in Japan
  and Taiwan; the patient counts are synthetic)

## 1. What it is

Every night each site counts how many of its own patients the criteria of each actively recruiting
ClinicalTrials.gov study in its therapeutic areas would leave. It uses the automatic compile and lake counts of
COHORT's trial simulation (`services/orchestrator/scenarios/trials.py`). Only aggregates leave the site, as one
signed feed per site and night:

- eligible now, new per month, a 12-month enrolment band, the target enrolment, criteria counted of total;
- the top three exclusions (the drops between counted criteria);
- every count rounded to the nearest 10, fewer than 10 shown as `<10`, and rates dropped next to a small cell.

A hub verifies each site's Ed25519 signature and shows the feeds to sponsors and CROs on one dashboard (filters for
condition, phase, site and minimum eligible; en, ja, zh-TW). A sponsor that wants a protocol answered sends it, and
the site's FEAS answers it as today.

No patient-level data, no identifiers and no free text from the record ever leave the site. The CGRD approval covers
research use; resale of patient-level data is outside it, so the product is aggregate by construction
(`tb_common.opportunity.guard` refuses any other key and any unrounded count before signing).

## 2. Revenue lines (for the commercial pack, T-745)

1. Per-protocol feasibility answer for a sponsor or CRO (the easiest first sale).
2. Annual dashboard subscription per sponsor or CRO, across all participating sites.
3. Site-selection fee when a sponsor picks a site from the board, paid through the normal clinical trial agreement.

Hospitals get a contractual revenue share. No fee per enrolled patient (kickback risk). No smart contracts: buyers
pay by invoice under an MSA, and the signed feed plus the sponsor's re-run is the provenance record.

## 3. Cards

| Card | Scope | Files | Acceptance | Depends on | Size | State |
| --- | --- | --- | --- | --- | --- | --- |
| **T-740** | Feed library (rounding, top exclusions, allow-list guard, Ed25519 sign and verify), the site's `build_feed` over `ctgov_search` and `simulate_one`, the hub dashboard page (en, ja, zh-TW), the tool (`keygen`, `sign`, `verify`, `dashboard`, `sample`) | `libs/tb_common/opportunity.py`, `services/orchestrator/scenarios/opportunity.py`, `services/opportunity_hub/*`, `tools/opportunity_feed.py`, `tests/unit/test_opportunity_feed.py` | unit tests: counts rounded, small cell drops rates, guard refuses an extra key or an unrounded count, a tampered feed fails verification; the sample page builds from a registry record offline | none | M | built (this PR) |
| **T-741** | Nightly OPPORTUNITY job: a job type and scheduler entry (default daily 03:45, after INGEST, behind the night gate), `site_params.yaml` `opportunity.conditions` and `per_condition`, the site key under `trialbox secrets`, the signed feed written to the outbox with an audit event; the registry mirror refreshed daily in `live` mode, from the refdata pack in `offline` | `services/orchestrator/scheduler.py`, job contracts, `site_params.yaml`, `tools/settings_wizard.py`, `tools/trialbox/secrets` | the job runs on the in-process box with the cassette and writes a feed that verifies; a held night writes no feed | T-740 | M | open |
| **T-742** | What the site publishes: a steward page with tonight's feed as a preview, per-condition and per-study switches, the threshold (never below 10), and the hand-over (HTTPS push to the hub on the egress allow-list, or a file the steward exports when the box is offline) | console page and permit row `opportunity.publish`, `services/orchestrator/outbox`, egress list | nothing leaves before the steward's switch is on; a switched-off study is absent from the next feed | T-741 | M | open |
| **T-743** | The hub: receive and verify feeds against a site key register, keep history, sponsor accounts with per-sponsor visibility, trend per trial, "send us your protocol" request routed to the sites' FEAS | `services/opportunity_hub/` (service, store, pages) | an unsigned or wrongly signed feed is refused; a sponsor sees only the sites that agreed to show it | T-740 | L | open |
| **T-744** | CGRD run: `build_feed` on the CGMH machine against CGRD for every recruiting AD and RA trial (then all of CGMH's areas), the site's review of the 20 largest automatic compiles, and the counts set against a manual feasibility on five trials | run report under `docs/plan/measurements/`, no code unless the run finds a bug | a signed CGRD feed that verifies on the hub; the five-trial comparison written down | T-741 (or the tool on its own) | M | open (prompt ready) |
| **T-745** | Commercial pack: price sheet, sponsor MSA and data licence for aggregate feeds, hospital revenue-share template, one-page provenance note | `docs/commercial/` | owner review | T-740 | S | open |

T-744 can start before T-741: the prompt in the project handover folder
(`/mnt/project-files/trialbox-handoff/opportunity-feed/`) runs `build_feed` once by hand on the CGMH machine.
