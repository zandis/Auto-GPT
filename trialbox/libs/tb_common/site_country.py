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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from tb_common import country_layer

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
    # 10C-13, 10C-15 (D-1229): how printed pages write a date and what a yearly report's year is
    # (tb_common.dates.PRINTED_STYLES, YEAR_BASES); written into a new site's settings, never into an installed one
    printed_dates: str = "western"
    year_basis: str = "calendar"
    # 10C-19 (D-1232): the consent record records consent by a representative and assent (the Japan profile:
    # GCP 第50条 代諾者 and アセント); the box's plan writes TB_CONSENT_PROXY=on for such a country
    consent_proxy: bool = False

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


def from_layer(country: str) -> CountryDefaults:
    """A country's set-up defaults read from its country layer (10C-25, D-1250; ``tb_common.country_layer``): the
    report language (P5), the retention rules (P1), the source, mapping and zone (P14), printed dates and the year
    (P9), consent by a representative (P11). Each is offered by the wizards and written into a new site's settings.
    A country whose layer is broken raises ``country_layer.LayerBroken`` (a ``ValueError`` naming the file and what is
    wrong): its set-up has no defaults to offer, never another country's."""
    v = country_layer.layer(country).value
    return CountryDefaults(
        country,
        v("P5", "report_language"),
        bool(v("P14", "one_zone", False)),
        v("P1", "retention_rules"),
        v("P14", "data_source_type"),
        v("P14", "mapping"),
        (),
        v("P9", "printed_dates", "western"),
        v("P9", "year_basis", "calendar"),
        consent_proxy=bool(v("P11", "consent_proxy", False)),
    )


class _Table(Mapping[str, CountryDefaults]):
    """The set-up defaults by country answer. A country with a layer is read from it when asked (never at import), so
    a layer that cannot be used reaches that country's set-up only."""

    def __init__(self, fixed: dict[str, CountryDefaults]) -> None:
        self._fixed = fixed

    def __getitem__(self, key: str) -> CountryDefaults:
        if key in self._fixed:
            return self._fixed[key]
        if key in COUNTRIES:
            return from_layer(key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(COUNTRIES)

    def __len__(self) -> int:
        return len(COUNTRIES)


TABLE: Mapping[str, CountryDefaults] = _Table(
    {
        "tw": CountryDefaults("tw", "zh-TW", True, "tw", "csv", "mapping/tw_core/demo_his.yaml", TWPAS_QUESTIONS),
        "us": CountryDefaults("us", "en", False, None, None, None, ()),
        "other": CountryDefaults("other", None, False, None, None, None, ()),
    }
)  # every answer of COUNTRIES not written here is read from its country's layer (D-1250)

# the wizard's defaults before 10K-1, for an answers file with no country: report language zh-TW, retention from the
# report language (ja -> jp, else tw), source csv, the Taiwan mapping, the TWPAS questions asked; no zone (D-315)
LEGACY = CountryDefaults("", "zh-TW", False, None, "csv", "mapping/tw_core/demo_his.yaml", TWPAS_QUESTIONS)


def extends_another(mapping: str) -> bool:
    """Whether a shipped mapping (``mapping/<folder>/<file>``) itself extends another one: then it can be used only by
    name, never as the base of a site mapping (the adapter's loader takes one level of ``extends``)."""
    try:
        text = (MAPPING_ROOT / mapping).read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"^extends:", text, re.M) is not None


def reads_ssmix2(country: str | None) -> bool:
    """Whether a country's shipped mapping reads an SS-MIX2 storage: the box offers SS-MIX2 only there."""
    try:
        return defaults(country).data_source_type == "ssmix2" and bool(str(country or "").strip())
    except ValueError:
        return False


def defaults(country: str | None) -> CountryDefaults:
    """The defaults for a country answer; :data:`LEGACY` when there is none. Raises ``ValueError`` for an answer that
    is not one of :data:`COUNTRIES`."""
    key = str(country or "").strip().lower()
    if not key:
        return LEGACY
    if key not in COUNTRIES:
        raise ValueError(f"country {country!r}: one of {', '.join(COUNTRIES)}")
    return TABLE[key]


# the question in the three languages of the box, as the wizard's ClinicalTrials.gov question is printed (D-140)
QUESTION = {
    "en": "Country or region of this site: jp = Japan, tw = Taiwan, us = United States, other = another.\n"
    "  The report language, time zone, retention periods, data source and mapping offered next follow this answer.",
    "ja": "この施設の国・地域：jp = 日本、tw = 台湾、us = 米国、other = その他。\n"
    "  この後に示すレポートの言語、タイムゾーン、保存期間、患者データの取得元、対応表の既定値は、"
    "この答えをもとに設定されます。",
    "zh-TW": "本院所在的國家或地區：jp = 日本、tw = 臺灣、us = 美國、other = 其他。\n"
    "  接下來提供的報告語言、時區、保存期限、資料來源與對應檔預設值，都依此答案而定。",
}
