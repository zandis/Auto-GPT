"""Public data screened by the product: the public accuracy run's fetchers, item builders, scorer and plumbing proof.

The owner's order (2026-11-14): search all public data, then test it properly, through the product. This package
turns the public sets the catalogues mark usable by a product vendor into what an installed box screens:

* :mod:`.sources`  every file, its URL, its sha256 pin, its size and its licence; one pinned fetcher into
  ``.cache/public_accuracy`` (never committed), and the live records (ClinicalTrials.gov, jRCT, PMC, GDC) fetched
  singly, politely, with their retrieval date.
* :mod:`.sets`     one reader per set: TREC Clinical Trials 2021/2022/2023, SIGIR 2016 with the TrialGPT criterion
  labels, the Taiwan FDA trial list (zh-Hant, cleaned, paired with ClinicalTrials.gov by protocol number), jRCT,
  Chia, BioScope (clinical part), TCGA-Reports, MedTxt, ACI-Bench, MACCROBAT, PMC Chinese case reports (converted
  to Traditional characters, marked so), JMED-Personas, OpenTWBench.
* :mod:`.site`     the item builder: patients' notes as a site's charts in the hospital CSV feed (the ingest format
  ``tools/public_site.py`` uses, mapped by ``services/adapter/mapping/tw_core/demo_his.yaml``), each trial's criteria
  as a protocol the box compiles, and the gold kept OUTSIDE the site folder, joined by ids only after the run.
* :mod:`.score`    the box's per-patient answers against the gold: eligible lost, excluded caught, wrong exclusions,
  unanswered, per language and stratum, with exact (Clopper-Pearson) intervals; the compile agreement of the same
  trial in zh-Hant and English.
* :mod:`.box`      the plumbing proof on the stand-in models: an in-process box, the hospital CSV ingest, the
  compiler and SCREEN through a PRODUCTION gateway, behind model-guard, to the strict vLLM stand-ins. Never an
  accuracy result: the stand-ins answer from ``services/llm_stub``.
* :mod:`.plan`     the first real-model run's sample and the model calls it implies.

    python -m tools.public_accuracy fetch [--only trec,sigir,...]
    python -m tools.public_accuracy build --set trec --out DIR [--pairs N]
    python -m tools.public_accuracy dryrun --set trec --work DIR
    python -m tools.public_accuracy score --work DIR
"""
