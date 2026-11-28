"""What rc1 refuses on a PRODUCTION box (the owner's ruling of 2026-11-20 on #639 and D-1072; review R22-34).

rc1 is a supervised demonstration on synthetic or public data. It promises nothing about live patient lists, EDC
writes from screening, patient mail and downloads, ad hoc support exports, unattended updates or key ceremonies.
Where the product can refuse them, it does. This module is the one table of those refusals and the one question every
call site asks:

* :data:`REFUSALS` names each refusal, the functions that ask (its call sites), the message key, the test that
  proves the refusal, the audit event that records it, and the environments in which it is allowed.
  ``tests/unit/test_rc1_refusals_table.py`` enumerates this table: every row's sites ask :func:`check` or
  :func:`refused` with the row's name, every row's test exists, and every name asked anywhere in ``libs``,
  ``services`` and ``tools`` is a row. A seventh refusal is one more row, and the invariant test then requires its
  sites and its test.
* :data:`ALLOWED` is the owner's answer (D-1072; the integrator's go, comment 7079138866): DEV, TEST and VALIDATION
  allow the table's actions. Changing it is this one line. In VALIDATION an allowed act carries :data:`LABELLED`'s
  label (``rc1: "validation"``) in the audit record its site writes, where one is written (:func:`label`).
* The environment is ``TB_ENV`` by the one rule (``tb_common.config.environment_name``, D-127; :func:`environment`):
  an unset ``TB_ENV`` is PRODUCTION, and a name that is not a known environment is allowed nowhere. The check fails
  closed: a refusal name that is not in the table raises :class:`KeyError`, and no setting turns a refusal off.
* :data:`TEXTS` holds each message in en, ja and zh-TW for the command-line tools. The console shows the same words
  from its own catalogue (``console.i18n_rc1``); a test keeps the two equal.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: the environments a box can be in (``tb_common.policy.classes.Environment``; a test keeps the two equal). This module
#: imports the standard library only: the host's python3 runs ``trialbox ops`` and the support bundle with no other
KNOWN_ENVIRONMENTS = frozenset({"DEV", "TEST", "VALIDATION", "PRODUCTION"})
#: the owner's answer (D-1072; the integrator's go, comment 7079138866): where the table's actions are allowed. It
#: is the one line to change: every row takes it
ALLOWED = frozenset({"DEV", "TEST", "VALIDATION"})
#: allowed there, an act carries this label in the audit record a site writes for it (no new event name)
LABELLED = {"VALIDATION": {"rc1": "validation"}}
#: the languages of :data:`TEXTS`
LANGS = ("en", "ja", "zh-TW")


@dataclass(frozen=True)
class Refusal:
    """One row of the table."""

    #: the name every call site asks with
    name: str
    #: what is refused, in plain words
    what: str
    #: ``module:qualified function`` of each function that asks (the call sites)
    sites: tuple[str, ...]
    #: the message key, in :data:`TEXTS` and in the console's catalogue
    key: str
    #: ``tests/...py::test_name``, the test that proves the refusal
    test: str
    #: the audit event that records a refusal at its sites, or "none (...)" where no audit writer is reachable
    audit: str = ""
    #: the environments in which the action is allowed
    allowed: frozenset[str] = ALLOWED


_SITE_TESTS = "tests/unit/test_rc1_refusal_sites.py"
_CONSOLE_TESTS = "tests/console/test_rc1_guard.py"

REFUSALS: tuple[Refusal, ...] = (
    Refusal(
        name="live_patient_lists",
        what="a list of patients made from the box's records (screening, micro-batch, cohort, navigation, case), "
        "a stored one shown by the console, and a listed patient's chart number revealed",
        sites=(
            "orchestrator.scheduler:require_released",
            "orchestrator.app:reveal",
            "console.rc1_guard:Rc1Guard.lists_refused",
            "console.notify:_collect",
        ),
        key="rc1.live_patient_lists",
        audit="console.denied (the console); screen.reveal_refused (a reveal); none when a list job fails at its first "
        "step (follow-up for lane H's writer)",
        test=f"{_CONSOLE_TESTS}::test_no_live_patient_list_on_a_production_box",
    ),
    Refusal(
        name="edc_writes_from_screening",
        what="a value TrialBox owns pushed from the data core to an EDC (REDCap) or another source; a person's own "
        "EDC data entry is not refused",
        sites=("datacore.sync:_push",),
        key="rc1.edc_writes_from_screening",
        audit="none (follow-up for lane H's writer)",
        test=f"{_SITE_TESTS}::test_no_edc_write_from_screening_on_a_production_box",
    ),
    Refusal(
        name="patient_mail_and_downloads",
        what="a mail that carries a job's patient-level files, a patient-level file downloaded from the console, and "
        "the orchestrator's export of the registry with chart numbers",
        sites=(
            "mail_gateway.gateway:Gateway._still_current",
            "mail_gateway.gateway:Gateway._attempt",
            "orchestrator.app:registry_export",
            "console.rc1_guard:Rc1Guard.downloads_refused",
        ),
        key="rc1.patient_mail_and_downloads",
        audit="mail.failed (the gateway holds it at once); console.denied (the console); registry.export_refused (the "
        "orchestrator's export)",
        test=f"{_CONSOLE_TESTS}::test_no_patient_mail_or_download_on_a_production_box",
    ),
    Refusal(
        name="support_exports",
        what="an ad hoc support bundle (trialbox support-bundle)",
        sites=("tools.support_bundle:build",),
        key="rc1.support_exports",
        audit="none (follow-up for lane H's writer)",
        test=f"{_SITE_TESTS}::test_no_support_export_on_a_production_box",
    ),
    Refusal(
        name="unattended_updates",
        what="an update left to the quiet hour (an update a person runs now stays allowed)",
        sites=("tools.trialbox.ops:OpsRunner._one",),
        key="rc1.unattended_updates",
        audit="console.ops (the runner's result event)",
        test=f"{_SITE_TESTS}::test_no_unattended_update_on_a_production_box",
    ),
    Refusal(
        name="key_ceremonies",
        what="the backup key ceremony, the backup key pair (trialbox backup-keygen), and the KEK's rotation, ceremony "
        "record, escrow shares, restic key and pid map key (tools.keys; its init stays allowed, and so does the "
        "rotation of a passphrase KEK to a new passphrase from a root-only file or stdin, audited: D-1092)",
        sites=(
            "tools.backup_key_ceremony:run",
            "tools.trialbox.__main__:_backup_cmd",
            "tools.keys:cmd_rotate_kek",
            "tools.keys:cmd_ceremony_record",
            "tools.keys:cmd_escrow_shares",
            "tools.keys:cmd_restic_key",
            "tools.keys:cmd_rotate",
        ),
        key="rc1.key_ceremonies",
        audit="none (follow-up for lane H's writer)",
        test=f"{_SITE_TESTS}::test_no_key_ceremony_on_a_production_box",
    ),
)


class Rc1Refused(PermissionError):
    """Raised by :func:`check` when the action is refused on this box: the row and the environment."""

    def __init__(self, refusal: Refusal, environment: str) -> None:
        self.refusal = refusal
        self.environment = environment
        super().__init__(f"rc1 refuses {refusal.name} on a {environment} box ({refusal.key})")

    def say(self, lang: str = "en") -> str:
        """The refusal in ``lang`` (:data:`TEXTS`)."""
        return text(self.refusal.key, lang, environment=self.environment)


def row(name: str) -> Refusal:
    """The table's row ``name``. A name that is not a row raises :class:`KeyError`: a call site cannot ask about a
    refusal the table does not list."""
    for r in REFUSALS:
        if r.name == name:
            return r
    raise KeyError(f"rc1 refusal {name!r} is not in tb_common.rc1_refusals.REFUSALS")


def environment(env: Mapping[str, str] | None = None) -> str:
    """The box's environment by the one rule (``tb_common.config.environment_name``, D-127; a test keeps the two
    equal, and this one is here so the host's python3 needs no other module): unset is PRODUCTION."""
    e = env if env is not None else os.environ
    return (e.get("TB_ENV") or "PRODUCTION").strip().upper()


def refused(name: str, env: Mapping[str, str] | None = None) -> bool:
    """Whether the refusal ``name`` applies: True unless the environment is one of the row's ``allowed``. An unknown
    environment name is in no row's ``allowed``, so it is refused."""
    return environment(env) not in row(name).allowed


def check(name: str, env: Mapping[str, str] | None = None) -> None:
    """Raise :class:`Rc1Refused` when the refusal ``name`` applies; return otherwise."""
    r = row(name)
    e = environment(env)
    if e not in r.allowed:
        raise Rc1Refused(r, e)


def label(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The label an allowed act carries in its audit record: ``{"rc1": "validation"}`` in VALIDATION, else none."""
    return dict(LABELLED.get(environment(env), {}))


def host_env(box: Path | Mapping[str, str], env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a host tool (``trialbox ...``) asks with: the stricter of the box's and the caller's (the
    review of R22-34: ``TB_ENV=DEV trialbox support-bundle`` on a PRODUCTION box is refused). The box's is its
    ``deploy`` folder's ``.env`` (no ``TB_ENV`` in it is PRODUCTION, the one rule; a ``.env`` that is a folder or
    cannot be read is PRODUCTION too), or the settings a tool read from it (a mapping); the caller's is its own
    ``TB_ENV`` when set. Allowed only when both are in :data:`ALLOWED`; with neither, PRODUCTION. A missing ``.env``
    gives the caller's alone (the ruling's "missing is PRODUCTION" waits: it refuses every tool run from a checkout)."""
    seen: list[str] = []
    if isinstance(box, Path):
        f, written = box / ".env", ""
        if f.exists() or f.is_symlink():  # a missing file: the caller's alone (a checkout that is not a box)
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):  # a folder, unreadable, a dangling link: says nothing, PRODUCTION
                lines = []
            for line in lines:
                k, sep, v = line.partition("=")
                if sep and k.strip() == "TB_ENV" and not line.lstrip().startswith("#"):
                    written = v.strip().strip("\"'")
            seen.append(environment({"TB_ENV": written}))
    else:
        seen.append(environment({"TB_ENV": str(box.get("TB_ENV") or "").strip("\"'")}))
    own = (env if env is not None else os.environ).get("TB_ENV")
    if own:
        seen.append(environment({"TB_ENV": own}))
    if not seen:
        return {}
    return {"TB_ENV": next((e for e in seen if e not in ALLOWED), seen[0])}


_DEMO = {
    "en": "rc1 is a supervised demonstration on synthetic or public data.",
    "ja": "rc1 は合成データまたは公開データを使い、担当者の立ち会いのもとで行うデモンストレーションです。",
    "zh-TW": "rc1 是使用合成或公開資料、在人員監督下進行的展示。",
}

#: message key -> {language -> text}; ``{environment}`` is the box's environment
TEXTS: dict[str, dict[str, str]] = {
    "rc1.live_patient_lists": {
        "en": f"rc1 makes and shows no live patient list on a {{environment}} box. {_DEMO['en']} No list was made "
        "or shown.",
        "ja": f"rc1 は {{environment}} のボックスでは実際の患者リストを作成も表示もしません。{_DEMO['ja']}"
        "リストは作成も表示もしていません。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不產生也不顯示真實的病人名單。{_DEMO['zh-TW']}未產生或顯示任何名單。",
    },
    "rc1.edc_writes_from_screening": {
        "en": f"rc1 writes nothing from screening to the EDC on a {{environment}} box. {_DEMO['en']} Nothing was "
        "written.",
        "ja": f"rc1 は {{environment}} のボックスではスクリーニングの結果を EDC に書き込みません。{_DEMO['ja']}"
        "何も書き込んでいません。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不將篩選結果寫入 EDC。{_DEMO['zh-TW']}未寫入任何內容。",
    },
    "rc1.patient_mail_and_downloads": {
        "en": f"rc1 sends no mail with patient files and gives no patient file to download on a {{environment}} box. "
        f"{_DEMO['en']} Nothing was sent or downloaded.",
        "ja": f"rc1 は {{environment}} のボックスでは患者のファイルを付けたメールを送らず、患者のファイルのダウンロード"
        f"も提供しません。{_DEMO['ja']}何も送信もダウンロードもしていません。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不寄送附有病人檔案的郵件，也不提供病人檔案下載。{_DEMO['zh-TW']}"
        "未寄送或下載任何內容。",
    },
    "rc1.support_exports": {
        "en": f"rc1 makes no support bundle on a {{environment}} box. {_DEMO['en']} Nothing was written.",
        "ja": f"rc1 は {{environment}} のボックスではサポート用のバンドルを作りません。{_DEMO['ja']}"
        "何も書いていません。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不產生支援套件。{_DEMO['zh-TW']}未寫入任何內容。",
    },
    "rc1.unattended_updates": {
        "en": f"rc1 applies no update in the quiet hour on a {{environment}} box. {_DEMO['en']} Nothing was "
        "applied; an update a person runs now is still allowed.",
        "ja": f"rc1 は {{environment}} のボックスでは利用の少ない時間帯に更新を自動で適用しません。{_DEMO['ja']}"
        "何も適用していません。担当者がその場で行う更新は引き続きできます。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不在離峰時段自動套用更新。{_DEMO['zh-TW']}未套用任何更新；"
        "由人員當下執行的更新仍可進行。",
    },
    "rc1.key_ceremonies": {
        "en": f"rc1 holds no backup key ceremony and makes no backup key on a {{environment}} box. {_DEMO['en']} "
        "Nothing was generated.",
        "ja": f"rc1 は {{environment}} のボックスではバックアップ鍵の手続きを行わず、バックアップ鍵も作りません。"
        f"{_DEMO['ja']}何も生成していません。",
        "zh-TW": f"rc1 在 {{environment}} 主機上不進行備份金鑰儀式，也不產生備份金鑰。{_DEMO['zh-TW']}未產生任何內容。",
    },
}


def text(key: str, lang: str = "en", **values: str) -> str:
    """The message ``key`` in ``lang`` (en, ja, zh-TW; English when the language is not one of them), filled."""
    t = TEXTS[key]
    return (t.get(lang) or t["en"]).format(**values)
