"""U5-1 (card U-5): the one list of the site information a box may still need (``tb_common.site_needs``).

The list is the single source the installer, ``doctor``, the page "Information still needed" and the go-live gates
read. These tests hold it to the tree as it is:

* each name it reads is a setting the box declares or reads (``tb_common.config.DECLARED``, ``config._ENV_MAP``),
  a key of the settings schema, or a file the installer makes;
* at least one name of every group is written by the install (``tools/settings_wizard.py`` or ``tools/box/plan.py``),
  so no item waits on an answer nothing can give;
* every text is in en, ja and zh-TW, and the ja and zh-TW texts are not the English one;
* missing, stand-in and given are told apart, and a step's list holds exactly the needs before it.

Synthetic values only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tb_common import config, site_needs
from tb_common.site_needs import BY_KEY, LANGS, NEEDS, STEPS, WHO, all_texts, state, still_needed

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SOURCES = ("tools/settings_wizard.py", "tools/box/plan.py", "deploy/install.sh")


def _names() -> list[str]:
    return [name for n in NEEDS for group in n.answers for name in group]


def test_keys_are_unique_and_each_need_is_well_formed() -> None:
    assert len(BY_KEY) == len(NEEDS)
    for n in NEEDS:
        assert n.before and set(n.before) <= set(STEPS), n.key
        assert n.who in WHO, n.key
        assert n.answers and all(n.answers), n.key
        for name in (x for g in n.answers for x in g):
            assert name.startswith(site_needs.PREFIXES), name


def test_each_name_is_declared_or_in_the_settings_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "settings.schema.json").read_text(encoding="utf-8"))
    for name in _names():
        if name.startswith("env:"):
            known = name[4:] in config.DECLARED or name[4:] in config._ENV_MAP
            assert known, f"{name} is neither a declared setting nor one the box's environment reads"
        elif name.startswith("settings:"):
            node = schema
            for part in name[len("settings:") :].split("."):
                node = node["properties"][part]
        else:
            assert name == "file:secrets/backup.pub"
            assert "deploy/secrets/backup.pub" in (ROOT / "tools/trialbox/backup_schedule.py").read_text(
                encoding="utf-8"
            ) or "secrets/backup.pub" in (ROOT / "deploy/install.sh").read_text(encoding="utf-8")


def test_the_install_writes_at_least_one_name_of_every_group() -> None:
    text = "\n".join((ROOT / p).read_text(encoding="utf-8") for p in INSTALL_SOURCES)
    for n in NEEDS:
        for group in n.answers:
            bare = [x.split(":", 1)[1] for x in group]
            leaf = [b.rsplit(".", 1)[-1] for b in bare]
            assert any(b in text or lf in text for b, lf in zip(bare, leaf, strict=True)), f"{n.key}: {group}"


def test_every_text_is_in_three_languages() -> None:
    texts = list(all_texts())
    by_name: dict[str, dict[str, str]] = {}
    for name, lg, t in texts:
        assert t.strip(), f"{name} has no {lg} words"
        by_name.setdefault(name, {})[lg] = t
    for name, words in by_name.items():
        assert set(words) == set(LANGS), name
        assert words["ja"] != words["en"] and words["zh-TW"] != words["en"], name


def test_missing_stand_in_and_given_are_told_apart() -> None:
    office = BY_KEY["office_mailbox"]
    assert state(office, env={}) == "missing"
    assert state(office, env={"TB_SAE_OFFICE_MAILBOX": "  "}) == "missing"
    env = {"TB_SAE_OFFICE_MAILBOX": "admin@hospa.test"}
    assert state(office, env=env, stand_ins={"office_mailbox"}) == "stand_in"
    assert state(office, env=env) == "given"


def test_every_group_must_hold_and_any_name_in_a_group_is_enough() -> None:
    source = BY_KEY["data_source"]
    settings = {"data_source": {"type": "ssmix2"}}
    assert state(source, env={}, settings=settings) == "missing"
    assert state(source, env={"TB_SOURCE_DIR": "/srv/ssmix2"}, settings=settings) == "given"
    assert state(source, env={"TB_SOURCE_DSN": "x"}, settings=settings) == "given"
    assert state(source, env={"TB_SOURCE_DIR": "/srv/ssmix2"}, settings={}) == "missing"
    assert state(BY_KEY["backup_key"], env={}, files={"secrets/backup.pub"}) == "given"


def test_a_steps_list_holds_exactly_the_needs_before_it() -> None:
    every = still_needed(env={})
    assert [n.key for n, s in every] == [n.key for n in NEEDS] and {s for _, s in every} == {"missing"}
    for step in STEPS:
        got = {n.key for n, _ in still_needed(env={}, before=step)}
        assert got == {n.key for n in NEEDS if step in n.before}, step
    study = still_needed(env={"TB_SAE_OFFICE_MAILBOX": "office@hospa.test"}, before="study_open")
    assert study == []


def test_an_unknown_step_is_refused() -> None:
    with pytest.raises(ValueError):
        still_needed(env={}, before="go_live")
