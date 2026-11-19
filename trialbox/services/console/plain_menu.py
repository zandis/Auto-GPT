"""J-7 (D-1251; the journey review's R17, R18 and R22): a pruned "More", one name per page, and no job word or
variable name on a clinical page, behind the flag ``layout.plain_menu``.

* **The flag** ``layout.plain_menu`` (``tb_common.flags``, audited, off by default, no seed variable). It is read with
  the other layout flags in the console's one background read (``console.phone.LAYOUT_FLAGS``) and put in
  ``request.state.plain_menu``. Off, every page is as before, byte for byte.
* **The menu** (``templates/_nav.html``, between ``{#J7#}`` and ``{#/J7#}``): duplicates, "Overview", the Admin page's
  own tabs and the legacy pilot entries leave "More"; each page that leaves is reached from the page it belongs to
  (links on existing pages: "New request" on the feasibility reports, "Consent explainer" on the study's IRB page,
  "Check one patient" on the weekly list and the candidate registry, each shown by ``console.app.may_act``, the rule
  the target page uses to offer its action); the steward's top bar has four entries. A menu is not a permission: no
  route, guard or ``permit`` row changes.
* **One name per page** and **plain words**: :func:`key` swaps a text key for its plain one (:data:`SAME_FOR_ALL`,
  every role) or, for a clinical role, for one without a variable name (:data:`CLINICAL_ONLY`; the administrator
  keeps the name of the setting to change). Templates ask ``tp(key)``; with the flag off ``tp`` is ``t``.
"""

from __future__ import annotations

from console import i18n_plain
from console.i18n import CATALOGUES

FLAG = "layout.plain_menu"
#: the clinical roles (the journey review's R22): they never see a job type code, a state machine word, a field or
#: variable name or an internal id's label on the pages they use
CLINICAL = ("coordinator", "investigator", "viewer")

#: text key -> its plain key, for every role (R18: one name per page; R22: the job words of the review's table)
SAME_FOR_ALL: dict[str, str] = {
    # one name per page: the menu's label, the page's title and its heading from one key
    "wb.crc.title": "nav.studies",
    "home.studies": "nav.studies",
    "nav.reports": "reports.title",
    "nav.jobs": "guide.page.jobs",
    "jobs.title": "guide.page.jobs",
    "nav.restore_hold": "flags.title",
    "nav.case": "pm.case.title",
    "case.title": "pm.case.title",
    "nav.protocol": "protocol.title",
    "nav.consent": "consent.title",
    "nav.registry": "registry.title",
    # no job word: the code of a job type, "ruleset", a mail command
    "week.meta": "pm.week.meta",
    "feas.meta": "pm.feas.meta",
    "col.ruleset": "pm.col.ruleset",
    "col.job": "pm.col.job",
    "reports.run": "pm.reports.run",
    "request.feas": "pm.request.feas",
    "request.screen": "pm.request.screen",
    "request.free.help": "pm.request.free.help",
    "request.version": "pm.request.version",
    "request.no_rulesets": "pm.request.no_rulesets",
    "registry.help": "pm.registry.help",
    "registry.promote": "pm.registry.promote",
    "registry.promote.help": "pm.registry.promote.help",
    "registry.source.screen": "pm.registry.source.screen",
    "registry.source.case": "pm.case.title",
    "case.help": "pm.case.help",
    "consent.help": "pm.consent.help",
    "protocol.help": "pm.protocol.help",
    "protocol.ruleset": "pm.protocol.ruleset",
    "job.start_feas": "pm.job.start_feas",
}

#: text key -> its plain key, for a clinical role only: the same sentence without the setting's variable name (the
#: administrator, who sets it, keeps the name) or the data class
CLINICAL_ONLY: dict[str, str] = {
    "footer": "pm.footer",
    "sae.no_mailbox": "pm.sae.no_mailbox",
    "feas.ct.none.unset": "pm.feas.ct.none.unset",
    "feas.ct.none.unknown": "pm.feas.ct.none.unknown",
}

#: the words of a job type on the list of runs, for the types a clinical role starts (any other type is shown as it is)
JOB_TYPES = ("FEAS", "SCREEN", "CASE")


def key(on: bool, role: str | None, text_key: str) -> str:
    """The key a page shows for ``text_key``: itself with the flag off; else its plain key."""
    if not on:
        return text_key
    if role in CLINICAL and text_key in CLINICAL_ONLY:
        return CLINICAL_ONLY[text_key]
    return SAME_FOR_ALL.get(text_key, text_key)


for _lang, _cat in (("en", i18n_plain.EN), ("ja", i18n_plain.JA), ("zh-TW", i18n_plain.ZH)):
    CATALOGUES[_lang].update(_cat)
