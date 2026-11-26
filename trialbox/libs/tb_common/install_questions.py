"""The install's questions as data (M1; D-1280; ``docs/plan/design/install-questions-cut.md``): one row per question of
the old terminal path (57), its rule, and where it went; the four asked before the install; what is offered once it has
started. The installer, the page "Information still needed" and the tests read this one table.

A new question is a row here, and the count test fails on a fifth asked or a twelfth offered one. A prompt is allowed
only where a wrong default could harm a patient, lose data or expose data.

Standard library only: the host's ``python3`` imports it before any image is loaded.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from tb_common import site_needs

RULES = ("drop", "detect", "derive", "default", "merge", "defer")
MAX_ASKED, MAX_OFFERED = 4, 11


@dataclass(frozen=True)
class Old:
    """One question of the old path. ``to``: ``A1`` to ``A4`` or ``B1`` to ``B7`` (shown there), ``page`` (asked by the
    step that needs it), or ``-`` (nothing reads it, or nobody has to answer)."""

    key: str
    rule: str
    to: str
    how: str


# the wizard's 53 entries, then install.sh's four prompts (prompt:*)
OLD: tuple[Old, ...] = (
    Old("country", "drop", "-", "the country of the time zone"),
    Old("site_id", "derive", "B1", "from the hospital's name"),
    Old("site_name", "default", "B1", "a marked stand-in name"),
    Old("tz", "detect", "A2", "the host's zone"),
    Old("locale", "merge", "A1", "the language"),
    Old("printed_dates", "derive", "A2", "the country of the zone"),
    Old("year_basis", "derive", "A2", "the country of the zone"),
    Old("contact", "derive", "A3", "the administrator's mail"),
    Old("internal_domains", "derive", "A3", "the domain of the administrator's mail"),
    Old("intake_address", "derive", "A3", "trialbox@ that domain"),
    Old("senders", "derive", "A3", "the administrator's mail"),
    Old("physicians", "derive", "A3", "the administrator's mail"),
    Old("reviewers", "derive", "A3", "the administrator's mail"),
    Old("alliance_sites", "default", "-", "none"),
    Old("data_source_type", "merge", "B3", "with the records' folder"),
    Old("data_source_path", "derive", "-", "a constant"),
    Old("data_source_host_dir", "merge", "B3", "with the records' kind"),
    Old("ssmix2_order_numbers", "defer", "page", "the first SS-MIX2 run"),
    Old("data_source_dsn_env", "derive", "-", "a constant"),
    Old("mapping", "derive", "B3", "the country and the kind of source"),
    Old("mrn_regex", "derive", "B4", "the chart-number rule"),
    Old("chartno_rule", "merge", "B4", "one example as printed, or read from the first records"),
    Old("registry_type", "default", "-", "none"),
    Old("registry_path", "default", "-", "none"),
    Old("departments", "drop", "-", "the shipped department list, then the records"),
    Old("practitioners", "defer", "page", "who to screen, by doctor"),
    Old("llm_mode", "detect", "-", "the graphics card"),
    Old("cloud_enabled", "default", "-", "no"),
    Old("attachment_encryption", "default", "-", "link"),
    Old("console_url", "derive", "B2", "the box's name"),
    Old("twpas_enabled", "default", "-", "off"),
    Old("twpas_org_id", "defer", "page", "when TWPAS is turned on"),
    Old("alliance_root", "default", "-", "no"),
    Old("alliance_root_address", "defer", "page", "when the box joins an alliance"),
    Old("cohort_rulesets", "default", "-", "every approved one"),
    Old("smtp_host", "detect", "B6", "the domain's mail exchanger, proposed"),
    Old("smtp_port", "detect", "B6", "587, 465 or 25, whichever answers"),
    Old("imap_host", "defer", "page", "reading request mail"),
    Old("imap_port", "detect", "-", "993 or 143, whichever answers"),
    Old("imap_user", "derive", "-", "the local part of the intake address"),
    Old("mta_authserv_id", "defer", "page", "reading request mail"),
    Old("tls_hostname", "derive", "B2", "the box's name"),
    Old("sae_office_mailbox", "merge", "B6", "the administrator's mail until given"),
    Old("new_year_break", "derive", "A2", "the country's"),
    Old("tls_mode", "merge", "B7", "the box's own"),
    Old("tls_cert_file", "merge", "B7", "with the certificate"),
    Old("tls_key_file", "merge", "B7", "with the certificate"),
    Old("retention_rules", "drop", "-", "the country's"),
    Old("logs_days", "default", "-", "the rules'"),
    Old("mail_log_days", "default", "-", "the rules'"),
    Old("outputs_days", "default", "-", "the rules'"),
    Old("attachments_days", "default", "-", "the rules'"),
    Old("ctgov_mode", "detect", "-", "offline; live only by --ctgov"),
    Old("prompt:ctgov", "detect", "-", "offline; live only by --ctgov"),
    Old("prompt:tls_hostname", "derive", "B2", "the box's name"),
    Old("prompt:sae_office_mailbox", "merge", "B6", "the administrator's mail until given"),
    Old("prompt:start", "drop", "-", "an install starts"),
)


@dataclass(frozen=True)
class Question:
    """One question of today. ``needs``: the items of ``site_needs`` it fills; the gate it holds is theirs."""

    key: str
    needs: tuple[str, ...]
    rule: str  # how its default is made
    title: Mapping[str, str]
    default: Mapping[str, str]


def _t(en: str, ja: str, zh: str) -> dict[str, str]:
    return {"en": en, "ja": ja, "zh-TW": zh}


#: asked before the install starts (D-1280): the language, the time zone, the first administrator, the passphrase
ASKED: tuple[Question, ...] = (
    Question("A1", (), "default", _t("Language", "言語", "語言"),
             _t("the host's language", "機器の言語", "本機的語言")),
    Question("A2", (), "detect", _t("Time zone", "タイムゾーン", "時區"),
             _t("the host's time zone", "機器のタイムゾーン", "本機的時區")),
    Question("A3", (), "default", _t("The first administrator", "最初の管理者", "第一位管理員"),
             _t("the user name from the mail address", "メールアドレスから作るユーザー名", "由郵件地址產生的帳號")),
    Question("A4", (), "detect", _t("The key passphrase", "鍵のパスフレーズ", "金鑰密語"),
             _t("not asked where the machine has a security chip", "セキュリティチップがあれば聞きません",
                "有安全晶片的機器不詢問")),
)  # fmt: skip

#: offered once the install has started; the install waits for none of them
OFFERED: tuple[Question, ...] = (
    Question("B1", ("site_name",), "default", _t("The hospital's name", "病院の名前", "醫院名稱"),
             _t("a marked stand-in name", "目印の付いた仮の名前", "標記過的暫定名稱")),
    Question("B2", (), "detect", _t("The box's name on the network", "ネットワーク上の名前", "在網路上的名稱"),
             _t("the host's name", "機器のホスト名", "本機的主機名稱")),
    Question("B3", ("data_source",), "default",
             _t("Where the records come from", "診療データの取得元", "病歷資料的來源"),
             _t("the sample hospital for now; nothing on a box in use", "当面は見本の病院（本番の機械では未設定）",
                "暫用示範醫院（正式機器未設定）")),
    Question("B4", ("chart_number",), "detect",
             _t("How a chart number is written", "患者 ID（カルテ番号）の書き方", "病歷號的寫法"),
             _t("as written, until confirmed", "確認するまでは書かれたとおり", "確認前照原樣")),
    Question("B5", ("backup_target", "backup_alarm", "audit_share"), "detect",
             _t("Where backups and the audit record go", "バックアップと監査記録の保存先", "備份與稽核紀錄的存放處"),
             _t("on this machine for now", "当面はこの機械の中", "暫存於本機")),
    Question("B6", ("mail_relay", "office_mailbox"), "detect",
             _t("Mail: the relay and the trial office's mailbox", "メール：中継サーバーと治験事務局の宛先",
                "郵件：轉送伺服器與試驗辦公室信箱"),
             _t("no mail for now; the administrator's mail for the office",
                "当面はメールを送りません（事務局の宛先は管理者）", "暫不寄信（辦公室先用管理員信箱）")),
    Question("B7", ("certificate",), "default", _t("The certificate", "証明書", "憑證"),
             _t("the box's own", "機械自身のもの", "本機自有")),
)  # fmt: skip


def gate_of(q: Question) -> tuple[str, ...]:
    """The steps ``q`` holds until it is filled, in the order of ``site_needs.STEPS``; empty: it holds none."""
    held = {s for k in q.needs for s in site_needs.BY_KEY[k].before}
    return tuple(s for s in site_needs.STEPS if s in held)


def table(lang: str = "en", *, open_keys: Collection[str] = ()) -> list[dict[str, Any]]:
    """The one table, generated: a row per question with its default, its rule, the gate it holds and whether it is
    still open (``open_keys``: the open items of ``site_needs``)."""
    lg = lang if lang in site_needs.LANGS else "en"
    return [
        {
            "key": q.key,
            "group": group,
            "title": q.title[lg],
            "default": q.default[lg],
            "rule": q.rule,
            "gate": [site_needs.STEPS[s][lg] for s in gate_of(q)],
            "open": any(k in open_keys for k in q.needs),
            "replaces": [o.key for o in OLD if o.to == q.key],
        }
        for group, qs in (("asked", ASKED), ("offered", OFFERED))
        for q in qs
    ]
