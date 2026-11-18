"""The site's country or region and every set-up default that follows from it (10K-1): one table, read by the settings
wizard (``tools.settings_wizard``), the box's plan (``tools.box.plan``) and the box's first-run page.

The first question of both wizards is the country: Japan, Taiwan, the United States, or another country. Each later
default (report language, time zone, retention rules, data source, mapping, and which insurer questions are asked
at all) is read from :data:`TABLE`, and only from there. Where the repository holds no value for a country the entry
is ``None``: the question is asked without a default and an empty answer is an error, never another country's value.

Where each value comes from (no value here is invented):

* report language: the three catalogues (``tb_common.box_answers.LANGUAGES``; reports read ``site.locale`` through
  ``orchestrator.i18n.norm_lang``);
* time zone: for a country with one zone only (Japan, Taiwan), the zone its shipped mapping states (``tz:``, read
  from the file: no zone is written in code, D-315); the United States has several, so the zone is asked with no
  default;
* retention: ``tb_common.retention.DEFAULTS`` (D-138) has ``jp`` and ``tw`` only; no other country's rules exist in
  the repository, so the days are asked;
* data source and mapping: Japan's shipped site mapping is ``mapping/jp_core/ssmix2_site.yaml`` (source ``ssmix2``,
  ``tz: Asia/Tokyo``); Taiwan's is ``mapping/tw_core/demo_his.yaml`` (source ``csv``, ``tz: Asia/Taipei``); there
  is none for another country;
* insurer questions: TWPAS and the NHI hospital code are Taiwan's National Health Insurance; no other country's
  insurer or registry submission exists in the repository.

**An answers file without** ``country`` (every file written before 10K-1, and every installed box) reads exactly as
before: :data:`LEGACY` is the set of defaults the wizard had then, and the country table is not consulted.

Standard library only: the host's ``python3`` imports it before any image is loaded (``tools.box.plan``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

COUNTRIES = ("jp", "tw", "us", "other")
# the adapter's shipped mappings (services/adapter/mapping), beside libs/ in the tree and in every image (/app)
MAPPING_ROOT = Path(__file__).resolve().parents[2] / "services" / "adapter"
_TZ_LINE = re.compile(r"^tz:\s*([A-Za-z_]+/[A-Za-z_]+)\s*(?:#.*)?$", re.M)
# the SS-MIX2 reader's order-number keys (D-594; adapter.sources.ssmix2.source.ORDER_KEYS, a test keeps them equal)
SSMIX2_ORDER_NUMBERS = ("unique", "per_day")
TWPAS_QUESTIONS = ("twpas_enabled", "twpas_org_id")


@dataclass(frozen=True)
class CountryDefaults:
    country: str
    locale: str | None  # the report language; None: asked, no default
    one_zone: bool  # the country has one time zone: its shipped mapping's ``tz`` is the default (see :attr:`tz`)
    retention_rules: str | None  # a key of tb_common.retention.DEFAULTS; None: the repository has none, days asked
    data_source_type: str | None  # None: asked, no default
    mapping: str | None  # None: asked, no default
    insurer_questions: tuple[str, ...]  # the wizard's insurer and registry questions asked for this country

    @property
    def tz(self) -> str | None:
        """The zone default: the one the country's shipped mapping states (``tz:``), for a country with one zone only.
        None (asked, no default; D-315) for a country with several, or when the mapping cannot be read."""
        if not (self.one_zone and self.mapping):
            return None
        try:
            found = _TZ_LINE.search((MAPPING_ROOT / self.mapping).read_text(encoding="utf-8"))
        except OSError:
            return None
        return found.group(1) if found else None


TABLE: dict[str, CountryDefaults] = {
    "jp": CountryDefaults("jp", "ja", True, "jp", "ssmix2", "mapping/jp_core/ssmix2_site.yaml", ()),
    "tw": CountryDefaults("tw", "zh-TW", True, "tw", "csv", "mapping/tw_core/demo_his.yaml", TWPAS_QUESTIONS),
    "us": CountryDefaults("us", "en", False, None, None, None, ()),
    "other": CountryDefaults("other", None, False, None, None, None, ()),
}

# the wizard's defaults before 10K-1, for an answers file with no country: report language zh-TW, retention from the
# report language (ja -> jp, else tw), source csv, the Taiwan mapping, the TWPAS questions asked; no zone (D-315)
LEGACY = CountryDefaults("", "zh-TW", False, None, "csv", "mapping/tw_core/demo_his.yaml", TWPAS_QUESTIONS)


def defaults(country: str | None) -> CountryDefaults:
    """The defaults for a country answer; :data:`LEGACY` when there is none. Raises ``ValueError`` for an answer that
    is not one of :data:`COUNTRIES`."""
    key = str(country or "").strip().lower()
    if not key:
        return LEGACY
    if key not in TABLE:
        raise ValueError(f"country {country!r}: one of {', '.join(COUNTRIES)}")
    return TABLE[key]


# the question in the three languages of the box, as the wizard's ClinicalTrials.gov question is printed (D-140)
QUESTION = {
    "en": "Country or region of this site: jp = Japan, tw = Taiwan, us = United States, other = another.\n"
    "  The report language, time zone, retention periods, data source and mapping offered next follow this answer.",
    "ja": "この施設の国・地域：jp = 日本、tw = 台湾、us = 米国、other = その他。\n"
    "  この後に示すレポートの言語、タイムゾーン、保存期間、データ取得元、マッピングの既定値はこの答えに従います。",
    "zh-TW": "本院所在的國家或地區：jp = 日本、tw = 臺灣、us = 美國、other = 其他。\n"
    "  接下來提供的報告語言、時區、保存期限、資料來源與對應檔預設值，都依此答案而定。",
}
