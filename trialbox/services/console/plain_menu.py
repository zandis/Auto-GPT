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
  every role) or, for an account that does not keep the box's internal names (:data:`KEEPS_INTERNAL_NAMES`, a
  ``permit`` question, never a role name), for one without a variable name or the data class (:data:`CLINICAL_ONLY`;
  the administrator keeps the name of the setting to change). Templates ask ``tp(key)``; with the flag off ``tp``
  is ``t``.
"""

from __future__ import annotations

from typing import get_args

from tb_common.authz import permit
from tb_contracts import Job

from console import i18n_plain
from console.i18n import CATALOGUES

FLAG = "layout.plain_menu"
#: the capability that keeps the box's internal names (the data class, a setting's variable name): reading the audit
#: trail's provenance (``tb_common.authz``: the administrator, the data steward, the privacy office). Every other
#: account, the clinical roles among them (the journey review's R22), reads the plain sentence
KEEPS_INTERNAL_NAMES = "audit.provenance"

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
    # a link says the name of the page it opens, or the heading of the section it opens (the coordinator's review)
    "account.notice_settings": "notices.title",
    "admin.manage": "users.title",
    "admin.create": "users.add",
    "home.send_protocol": "protocol.title",
    "site.link.protocol": "protocol.title",
    "team.scope.change": "setup.who.title",
    "home.open_report": "feas.title",
    "home.open_week": "nav.week",
    "adm.users.identity": "identity.title",
    "adm.identity": "identity.title",
    "admin.overview": "nav.overview",
    "site.nav.ready": "site.ready.title",
    "site.nav.start": "site.start.title",
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
    "registry.source.screen": "pm.jobtype.SCREEN",
    "registry.source.case": "pm.jobtype.CASE",
    "case.help": "pm.case.help",
    "consent.help": "pm.consent.help",
    "protocol.help": "pm.protocol.help",
    "protocol.ruleset": "pm.protocol.ruleset",
    "job.start_feas": "pm.job.start_feas",
}

#: text key -> its plain key, for an account without :data:`KEEPS_INTERNAL_NAMES`: the same sentence without the
#: setting's variable name (the administrator, who sets it, keeps the name) or the data class
CLINICAL_ONLY: dict[str, str] = {
    "footer": "pm.footer",
    "sae.no_mailbox": "pm.sae.no_mailbox",
    "feas.ct.none.unset": "pm.feas.ct.none.unset",
    "feas.ct.none.unknown": "pm.feas.ct.none.unknown",
}

#: every job type there is (the contract's own list, ``tb_contracts.Job.type``; a test keeps it equal to the
#: orchestrator's ``scenarios.registry``): the list of runs names each in words (``pm.jobtype.<TYPE>``); a type not in
#: it is named "Other run", never by its code
JOB_TYPES: tuple[str, ...] = get_args(Job.model_fields["type"].annotation)
#: the suffixes of the ``pm.jobtype.`` keys: every type, and the neutral word
JOB_TYPE_WORDS = (*JOB_TYPES, "other")


#: the next step's button on a study card (``console.home.study_card``) says where it goes: the name of the page, or
#: of the section, its kind opens (instead of "Go")
NEXT_GO: dict[str, str] = {
    "approve": "s20.title",
    "feas": "request.title",
    "screen": "request.title",
    "site": "feas.s8",
    "contact": "nav.week",
    "week": "nav.week",
}


def next_go_key(kind: str) -> str:
    """The text key of the next step's button of ``kind`` ("Go" for a kind not listed)."""
    return NEXT_GO.get(kind, "next.go")


def job_type_word(job_type: str) -> str:
    """The suffix of ``job_type``'s ``pm.jobtype.`` key on the list of runs ("other" for a type not listed)."""
    return job_type if job_type in JOB_TYPES else "other"


def key(on: bool, role: str | None, text_key: str) -> str:
    """The key a page shows for ``text_key``: itself with the flag off; else its plain key."""
    if not on:
        return text_key
    if role is not None and text_key in CLINICAL_ONLY and not permit(role, KEEPS_INTERNAL_NAMES).allowed:
        return CLINICAL_ONLY[text_key]
    return SAME_FOR_ALL.get(text_key, text_key)


for _lang, _cat in (("en", i18n_plain.EN), ("ja", i18n_plain.JA), ("zh-TW", i18n_plain.ZH)):
    CATALOGUES[_lang].update(_cat)
