"""The country layer's lines of a night's "Site profile" section (10C-25, D-1250): what the Japan profile offers or
turns on at this site, the value in force for each, and where it comes from.

* ``site``: a setting the site made (in its settings or its environment). It wins over the layer: a named person's
  recorded choice, as the site set-up store wins over the site profile's table (D-1233).
* ``layer``: the layer's own value, read at run time (the holidays, the New Year break the site did not change, the
  eGFR equation, the SAE rule set shown before one is chosen, the committees, the YJ stems).
* ``unset``: a set-up value the site's settings do not name (printed dates, the year, consent by a representative):
  the value before the layer, never the layer's (D-1229). The set-up wizards offer the layer's value and write it.

Configuration only: no patient data. Empty for a site whose country has no layer, so such a site's page is as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from datacore import lifecycle, proxy_consent
from tb_common import committees, country_layer, dates, derived, workdays

FROM_LAYER, FROM_SITE, UNSET = "layer", "site", "unset"
SOURCES = (FROM_LAYER, FROM_SITE, UNSET)
KEYS = ("printed_dates", "year_basis", "consent_proxy", "new_year_break", "holiday_list", "ingredient_stems",
        "ingredient_file", "egfr", "sae_rule_set", "committees")  # fmt: skip


def _word(v: Any) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    return "" if v is None else str(v)


def in_force(country: str | None, site: object, env: Mapping[str, str]) -> list[dict[str, str]]:
    """One row per :data:`KEYS`: ``key``, ``part``, ``layer`` (the layer's value), ``value`` (in force) and ``source``
    (``site``, ``layer`` or ``unset``). Empty without a layer."""
    lay = country_layer.layer(country)
    if not lay.on:
        return []
    code = lay.country
    rows: list[dict[str, str]] = []

    def row(key: str, part: str, layer_value: Any, value: Any, source: str) -> None:
        rows.append({"key": key, "part": part, "layer": _word(layer_value), "value": _word(value), "source": source})

    style, basis = dates.site_dates(site)
    for key, value in (("printed_dates", style), ("year_basis", basis)):
        named = getattr(site, key, None) in (dates.PRINTED_STYLES if key == "printed_dates" else dates.YEAR_BASES)
        row(key, "P9", lay.value("P9", key), value, FROM_SITE if named else UNSET)
    named = bool(str(env.get(proxy_consent.ENV) or "").strip())
    row("consent_proxy", "P11", lay.value("P11", "consent_proxy"), proxy_consent.is_on(env),
        FROM_SITE if named else UNSET)  # fmt: skip
    cal = workdays.for_country(code, env)
    row("new_year_break", "P9", lay.value("P9", "new_year_break"), workdays.break_text(cal.new_year),
        FROM_SITE if cal.new_year_from == FROM_SITE else FROM_LAYER)  # fmt: skip
    row("holiday_list", "P9", lay.value("P9", "holiday_list"), lay.value("P9", "holiday_list"), FROM_LAYER)
    row("ingredient_stems", "P7", lay.value("P7", "ingredient_stems"), lay.value("P7", "ingredient_stems"), FROM_LAYER)
    own = bool(str(env.get("TB_JP_INGREDIENT_ATC") or "").strip())
    row("ingredient_file", "P7", "", "TB_JP_INGREDIENT_ATC" if own else "", FROM_SITE if own else UNSET)
    row("egfr", "P8", lay.value("P8", "egfr"), derived.egfr_for_site(code), FROM_LAYER)
    row("sae_rule_set", "P2", lay.value("P2", "sae_rule_set"), lifecycle.country_default(code), FROM_LAYER)
    row("committees", "P3", committees.on(code), committees.on(code), FROM_LAYER)
    return rows


def card(backend: object) -> dict[str, Any] | None:
    """The country layer's lines of a night's "Site profile" section (``/data-ops/batches/<id>``, D-1233): its
    country, version and digest (12 characters) and :func:`in_force`; None for a site whose country has no layer (the
    section is then as before). The country is the site's (``site.tz``, else ``TB_TZ``), as the site profile is
    checked against at night."""
    import os

    from tb_common.derived import country_of

    site = getattr(getattr(getattr(backend, "cfg", None), "settings", None), "site", None)
    tz = str(getattr(site, "tz", "") or os.environ.get("TB_TZ") or "")
    lay = country_layer.layer(country_of(tz))
    if not lay.on:
        return None
    return {"country": lay.country, "version": lay.version, "digest": lay.digest[:12],
            "rows": in_force(lay.country, site, os.environ)}  # fmt: skip
