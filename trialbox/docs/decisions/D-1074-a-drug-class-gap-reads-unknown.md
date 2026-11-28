# D-1074 A drug class's gap reads unknown, never False

- **Card:** INT-R2 (the integrator's builder; the owner's order, ring 0).
- **Decision:** a shipped drug class says which ATC branches hold no member; its `family` rows are the complement of that
  over the ATC grammar, so a code nobody placed reads unknown (D-113) and goes to the investigator. Duration criteria
  read the families too. An ATC code coarser than a family is inside it. An order with no ATC, not listed by its own
  code, is unknown where D-130 does not act (an exclusion, a `none`, a negated atom), in the criterion's window.
- **The owner's words:** what is not certain reads unknown, never True and never False; the list to confirm does not
  block.
- **What the owner re-approves:** the 15 drug ValueSets of seven rule sets with their SQL, CQL and ELM (listed codes
  unchanged), and RA-JAK's `terminology_release`.
- **Page:** `docs/handover/intr2-drug-class-gaps-2026-11-25.md`, with `excluded.md` in its folder.
