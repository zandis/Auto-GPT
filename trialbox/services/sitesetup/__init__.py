"""Site setup and data harmonization (TB-PLAN-04 step 5b, D-131, D-132, D-135).

Three questions (which trial, which patients could fit, where trial records live), one rule (a fact the model read
from a chart is *proposed*: it can only send a patient to "needs information" until a person confirms it), one
readiness page. Modules:

* :mod:`sitesetup.messy`: pure clean-up of messy sheets and dumps (fix what is safe, list the rest to check);
* :mod:`sitesetup.charts` and :mod:`sitesetup.ocr`: chart text from paste, .txt, Word, PDF or a scan, and the
  model's proposed facts beside their quotes;
* :mod:`sitesetup.store`: schema ``sitesetup`` of the trial database (inputs, facts, local codes, checks);
* :mod:`sitesetup.intake`, :mod:`sitesetup.mapping`, :mod:`sitesetup.publish`, :mod:`sitesetup.readiness`;
* :mod:`sitesetup.help`: XLSX templates in the site's language and the synthetic practice site.
"""
