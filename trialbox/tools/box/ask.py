"""The four questions of the install, on the terminal (M1; D-1280): the language, the time zone, the first administrator,
and the key passphrase only without a security chip (``deploy/box-install.sh`` reads that one itself: it is never in a
file). Everything else is derived, detected or at its default, and shown on "Information still needed".

Standard library only: the host's ``python3`` runs it before any image is loaded. No password is asked: the install
makes the administrator's first one and its enrolment code, and shows both once.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

from tb_common import install_questions, site_country
from tb_common.box_answers import LANGUAGES, MAILBOX, PLACEHOLDER_NAME, person_name

from tools.box.plan import Hardware, PlanError

TRIES = 5
TEXT: dict[str, dict[str, str]] = {
    "language": {"en": "1 of 4. Language (en, ja, zh-TW)", "ja": "", "zh-TW": ""},
    "tz": {
        "en": "2 of 4. Time zone",
        "ja": "4 問中 2. タイムゾーン",
        "zh-TW": "第 2 題（共 4 題）：時區",
    },
    "mail": {
        "en": "3 of 4. First administrator: mail address",
        "ja": "4 問中 3. 最初の管理者：メールアドレス",
        "zh-TW": "第 3 題（共 4 題）：第一位管理員的郵件地址",
    },
    "name": {"en": "        full name", "ja": "        氏名", "zh-TW": "        姓名"},
    "again": {
        "en": "That cannot be used; please type it again.",
        "ja": "使えません。もう一度入力してください。",
        "zh-TW": "無法使用，請再輸入一次。",
    },
    "passphrase": {
        "en": "4 of 4. This machine has no security chip: choose a passphrase that unlocks its keys.",
        "ja": "4 問中 4. この機械にはセキュリティチップがありません。鍵を開けるパスフレーズを決めてください。",
        "zh-TW": "第 4 題（共 4 題）：本機沒有安全晶片，請設定解開金鑰的密語。",
    },
    "offered": {
        "en": 'Nothing more is asked. These have a default now; give them later on the page "Information still needed":',
        "ja": "質問は以上です。次の項目は今は既定値です。後で「まだ必要な情報」ページで入力できます：",
        "zh-TW": "不再提問。以下項目目前為預設值，之後可在「尚需填寫的資料」頁面填寫：",
    },
}
#: the country of a zone, where a country has one zone (Japan, Taiwan); any other zone names none
_USER_BAD = re.compile(r"[^a-z0-9._-]+")


def host_language(env: Mapping[str, str]) -> str:
    text = (env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or "").lower().replace("_", "-")
    return "ja" if text.startswith("ja") else "zh-TW" if text.startswith("zh-tw") else "en"


def country_of_zone(tz: str) -> str:
    for c in site_country.COUNTRIES:
        try:
            if tz and site_country.defaults(c).tz == tz:
                return c
        except ValueError:  # that country's layer cannot be used: no defaults of it are offered
            continue
    return ""


def user_name(mail: str) -> str:
    """The user name from the mail's local part (``console.auth.check_username``, with room for "-admin")."""
    return (_USER_BAD.sub("", mail.split("@", 1)[0].lower()) or "admin")[:26]


def _zone(text: str) -> bool:
    try:
        ZoneInfo(text)
    except Exception:
        return False
    return bool(text)


def _one(prompt: Callable[[str], str], text: str, default: str, ok: Callable[[str], bool], again: str) -> str:
    for _ in range(TRIES):
        try:
            got = prompt(f"{text} [{default}]: " if default else f"{text}: ").strip() or default
        except EOFError:  # nothing more will be typed: a default is an answer, no default is a stop
            if default and ok(default):
                return default
            raise PlanError(f"{text.strip()}: no answer (the input ended); nothing was changed") from None
        if ok(got):
            return got
        print(again)
    raise PlanError(f"{text.strip()}: no usable answer; nothing was changed")


def four(
    hw: Hardware, prompt: Callable[[str], str] = input, env: Mapping[str, str] | None = None, environment: str = ""
) -> dict[str, Any]:
    """The answers (as ``tb_common.box_answers.parse`` reads them) of the first three questions; the fourth is the
    passphrase. Nothing is written here."""
    env = os.environ if env is None else env
    start = host_language(env)
    lang = _one(prompt, TEXT["language"]["en"], start, lambda v: v in LANGUAGES, TEXT["again"][start])
    again = TEXT["again"][lang]
    tz = _one(prompt, TEXT["tz"][lang], hw.host_tz if _zone(hw.host_tz) else "", _zone, again)
    mail = _one(prompt, TEXT["mail"][lang], "", lambda v: bool(MAILBOX.fullmatch(v)) and len(v) <= 254, again)
    name = _one(prompt, TEXT["name"][lang], "", lambda v: bool(person_name(v)), again)
    country = country_of_zone(tz)
    if not hw.tpm:
        print(TEXT["passphrase"][lang])
    return {
        "language": lang,
        "tz": tz,
        "owner_full_name": name,
        "owner_username": user_name(mail),
        "owner_email": mail.lower(),
        "site_name": PLACEHOLDER_NAME,
        "box_name": hw.hostname.lower(),
        "backup_kind": "later",
        "source": "later",
        **({"country": country} if country else {}),
        **({"environment": environment.upper()} if environment else {}),
    }


def offered_text(lang: str) -> str:
    lines = [TEXT["offered"][lang]]
    lines += [f"    {r['title']}: {r['default']}" for r in install_questions.table(lang) if r["group"] == "offered"]
    return "\n".join(lines)
