# 32. Trial-opportunity feed: plan addendum to TB-PLAN-06

- **Date:** 2026-11-12
- **Owner request:** 2026-11-12 (project thread "Plan monetizing hospital trial-opportunity data"): add to the plan,
  add cards, build it, a sample page, and later run CGRD against every actively recruiting trial for feasibility.
- **Numbers:** this addendum was drafted as file 31 with cards T-690 to T-695 and decision D-449. Those were taken
  (the scale review's cards T-687 to T-704; D-449 is T-203b's; file 31 is TB-PLAN-06.1). It is file 32, cards T-740 to
  T-745, decision D-467; the next free decision number is taken from `REGISTRY.md` at start.
- **Decision:** D-467 (`docs/decisions/D-467-trial-opportunity-feed.md`)
- **Sample page:** `python -m tools.opportunity_feed sample --out-dir DIR` (offline: the synthetic registry records of
  the compiler's cassettes, synthetic counts). The earlier artifact page predates the privacy review and is
  superseded.

## 1. What it is

Each site counts, for itself and as often as it likes, how many of its own patients the criteria of each actively
recruiting ClinicalTrials.gov study in its therapeutic areas would leave. It uses COHORT's automatic compile and the
FEAS lake counts (`services/orchestrator/scenarios/opportunity.py`). Only aggregates leave the site, as one signed feed
per site and **month** (D-467 has the rules in full):

- only studies on the steward's **approved list** are counted and published; an empty list publishes nothing; at most
  a declared number of studies per condition;
- a study with **fewer than 10** patients who may meet its criteria has **no row** (no `<10`, no 0); the feed says only
  "none", "some" or a rounded number of rows left out; a study that could not be counted is `null` with a reason code;
- every count is a multiple of 10; the new-per-month **rate comes only from the rounded yearly count** (none under 10 a
  year); the 12-month **band is simulated from rounded inputs** with a site secret seed and published rounded to 10;
  **no exact rate or band** leaves the site;
- the "criteria not matched most often" list publishes a drop only when it and its remainder are at least 10, with
  **complementary suppression** of a neighbouring step;
- **opted-out patients are not counted** (the opt-out register as of the job's receipt);
- the feed is **published monthly** (a declared period, never under 28 days); within a period the values do not change.

A recipient learns, per approved study and month, whether at least 10 patients may meet the counted criteria and that
number to the nearest 10, a rate and a band derived from rounded numbers only, and up to three rounded drops of at
least 10. A missing study has fewer than 10 or is not approved, and the recipient cannot tell which. The recipient
cannot learn an exact count, a count or drop under 10, one patient's effect on a given day, or anything about an
opted-out patient.

A hub checks each feed against the feed schema, verifies the site's Ed25519 signature against a site key register
(site id to key fingerprint and registered name; out-of-date feeds are marked) and shows the feeds to sponsors and CROs
on one dashboard (filters for condition, phase, site and minimum count; en, ja, zh-TW). A sponsor that wants a protocol
answered sends it, and the site's FEAS answers it as today.

No patient-level data, no identifiers and no free text from the record ever leave the site. The CGRD approval covers
research use; resale of patient-level data is outside it, so the product is aggregate by construction
(`tb_common.opportunity.validate` refuses anything else before signing and at the hub).

## 2. Revenue lines (for the commercial pack, T-745)

1. Per-protocol feasibility answer for a sponsor or CRO (the easiest first sale).
2. Annual dashboard subscription per sponsor or CRO, across all participating sites.
3. Site-selection fee when a sponsor picks a site from the board, paid through the normal clinical trial agreement.

Hospitals get a contractual revenue share. No fee per enrolled patient (kickback risk). No smart contracts: buyers
pay by invoice under an MSA, and the signed feed plus the sponsor's re-run is the provenance record.

## 3. Cards

| Card | Scope | Files | Acceptance | Depends on | Size | State |
| --- | --- | --- | --- | --- | --- | --- |
| **T-740** | Feed library (approved-list gate, row suppression under the floor, rounded rate and band, funnel rule with complementary suppression, monthly period, cap per condition, one schema, Ed25519 sign and verify with the fingerprint and period signed, site key register), the site's `build_feed` over `ctgov_search` and the FEAS counts without opted-out patients, the hub dashboard page (en, ja, zh-TW), the tool (`keygen`, `sign`, `verify`, `dashboard`, `sample`) | `libs/tb_common/opportunity.py`, `services/orchestrator/scenarios/opportunity.py`, `services/opportunity_hub/*`, `tools/opportunity_feed.py`, `tests/unit/test_opportunity_feed.py` | unit tests: the review's attacks (exact rate, band inversion, probe rows, day-to-day and funnel differencing, opted-out patient, unchecked fields, unescaped page, self-signed or replayed feed) stay closed; the sample page builds offline from the synthetic cassettes | none | M | built (this PR) |
| **T-741** | OPPORTUNITY job: a job type and scheduler entry (it may compute nightly, default 03:45 after INGEST behind the night gate, but publishes once per period through `publish_once`, D-467), `site_params.yaml` `opportunity.conditions`, the settings `TB_OPPORTUNITY_*`, the site key and band secret under `trialbox secrets`, the signed feed written to the outbox with an audit event; the registry mirror refreshed daily in `live` mode, from the refdata pack in `offline` | `services/orchestrator/scheduler.py`, job contracts, `site_params.yaml`, `tools/settings_wizard.py`, `tools/trialbox/secrets` | the job runs on the in-process box with the cassette and writes a feed that verifies; a held night writes no feed | T-740 | M | open |
| **T-742** | What the site publishes: a steward page with this period's feed as a preview, per-condition switches and the per-study approved list that `build_feed` already requires (`TB_OPPORTUNITY_APPROVED_FILE`), the threshold (never below 10), and the hand-over (HTTPS push to the hub on the egress allow-list, or a file the steward exports when the box is offline) | console page and permit row `opportunity.publish`, `services/orchestrator/outbox`, egress list | nothing leaves before the steward's switch is on; a switched-off study is absent from the next feed | T-741 | M | open |
| **T-743** | The hub: receive and verify feeds against a site key register, keep history, sponsor accounts with per-sponsor visibility, trend per trial, "send us your protocol" request routed to the sites' FEAS | `services/opportunity_hub/` (service, store, pages) | an unsigned or wrongly signed feed is refused; a sponsor sees only the sites that agreed to show it | T-740 | L | open |
| **T-744** | CGRD run: `build_feed` on the CGMH machine against CGRD for every recruiting AD and RA trial (then all of CGMH's areas), the site's review of the 20 largest automatic compiles, and the counts set against a manual feasibility on five trials | run report under `docs/plan/measurements/`, no code unless the run finds a bug | a signed CGRD feed that verifies on the hub; the five-trial comparison written down | T-741 (or the tool on its own) | M | open (prompt ready) |
| **T-745** | Commercial pack: price sheet, sponsor MSA and data licence for aggregate feeds, hospital revenue-share template, one-page provenance note | `docs/commercial/` | owner review | T-740 | S | open |

T-744 can start before T-741: the prompt in the project handover folder
(`/mnt/project-files/trialbox-handoff/opportunity-feed/`) runs `build_feed` once by hand on the CGMH machine.
