"""PHI guard (SPEC §7.4): regex + dictionary scan run on the full text before any cloud LLM call.

Any hit disables cloud for the job (the local model is used) and the audit records ``phi_guard_hit=true``. A clean
scan returns a :class:`PhiClearance` bound to the text's sha256; ``tb_common.llm`` accepts cloud calls only with a
clearance for exactly the text being sent. The guard errs on the side of hits (false positives only cost latency).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from tb_common import dates
from tb_common.crypto import sha256_text

# ~100 most frequent ROC surnames (covers > 95 % of the population) + common compound surnames
ROC_SURNAMES = set(
    "陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周徐蘇葉莊呂江何蕭羅高潘簡朱鍾游彭詹胡施沈余趙盧梁顏柯翁魏孫戴范方宋鄧"
    "杜傅侯曹薛丁卓阮馬董温唐藍蔣石古紀姚連馮歐程湯黄田康姜汪白鄒尤巫鐘黎涂龔嚴韓袁金童陸夏柳凃邵錢伍倪溫于"
)
ROC_COMPOUND = {"歐陽", "司馬", "諸葛", "上官", "張簡", "范姜", "周黃", "陳李", "江謝", "張廖"}
JP_SURNAMES = {
    "佐藤",
    "鈴木",
    "高橋",
    "田中",
    "伊藤",
    "渡辺",
    "山本",
    "中村",
    "小林",
    "加藤",
    "吉田",
    "山田",
    "佐々木",
    "山口",
    "松本",
    "井上",
    "木村",
    "林",
    "斎藤",
    "清水",
    "山崎",
    "森",
    "池田",
    "橋本",
    "阿部",
    "石川",
    "山下",
    "中島",
    "石井",
    "小川",
    "前田",
    "岡田",
    "長谷川",
    "藤田",
    "後藤",
    "近藤",
    "村上",
    "遠藤",
    "青木",
    "坂本",
    "斉藤",
    "福田",
    "太田",
    "西村",
    "藤井",
    "金子",
    "岡本",
    "藤原",
    "中野",
    "三浦",
    "原田",
    "中川",
    "松田",
    "竹内",
    "小野",
    "田村",
    "中山",
    "和田",
}
HONORIFIC = r"(?:先生|小姐|女士|太太|老先生|老太太|阿嬤|阿公|君|さん|様|氏|くん|ちゃん)"
PATIENT_WORD = r"(?:病人|患者|個案|病患|案主|受試者)"
KEYWORDS = re.compile(
    r"病歷號(?:碼)?|身分證(?:字號)?|身份證|姓名|出生日期|聯絡電話|住址|患者ID|カルテ番号|氏名|生年月日"
)
TW_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![0-9])")
PHONE = re.compile(
    r"(?<!\d)(?:\+886[-\s]?9\d{2}|09\d{2})[-\s]?\d{3}[-\s]?\d{3}(?!\d)|(?<!\d)\(?0[2-8]\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"
)
# NEW-B-43 (D-744): an English phone number (North American, British or any with a country code). The long forms
# anywhere; a seven-digit local number, and a number written without separators, only after a word that says it is a
# phone (``Tel``, ``phone (no.)``, ``mobile``, ``contact``, ``call``, ``pager``, ``T:`` ...). Separators never cross a
# line: a prompt's variables are scanned one per line. Clinical ranges (100-300 mg, 4.5-11.0), runs of doses or counts
# (250 500 1000), times (0800 1200), study, lot and kit numbers and a spaced lab code (JLAC10) have none of the shapes.
# One pattern for the note masker, the gate before a call (:func:`scan`) and the guard service's recognisers. Group
# ``v``: the number (the word stays).
_SP = r"[^\S\n]"  # a space or tab, never a line break
_DASH = r"[-.\u2010-\u2015\u2212]"  # hyphen, dot and the Unicode dashes
_SEP = rf"(?:{_DASH}|{_SP})"
_DATE_AFTER = r"(?:19|20)\d{2}[-./\s]\d{1,2}[-./\s]\d{1,2}"  # D-747: a date is never the rest of a phone number
_EN_PHONE_FULL = (
    # with its country code, at least nine digits, never a date after it (+0800 2026-11-15, job 001 2026-11-15):
    # "+" and the code (tel:+15550100133 too), or "00", the code and a separator (never 0012345678, an id)
    rf"(?=(?:[^\d\n]{{0,3}}\d){{9}})(?!(?:\+|00)\d{{1,4}}[-./\s(]{{0,2}}{_DATE_AFTER})"
    rf"(?:\+\d{{1,3}}{_SEP}?|(?<![\d.,])(?<!\d{_SP})00[1-9]\d{{0,2}}{_SEP})\(?\d{{1,4}}\)?(?:{_SEP}?\d{{2,4}}){{2,3}}"
    # North American: (area) or area and a dash, exchange, line; a leading 1 too
    rf"|(?:1{_DASH})?(?:\([2-9]\d{{2}}\){_SP}?|[2-9]\d{{2}}{_DASH})\d{{3}}{_DASH}\d{{4}}"
    # British national: the area code with a separator or in brackets, then the subscriber number
    rf"|(?<!\d{_SP})(?:\(0\d{{4}}\){_SP}?|0\d{{4}}{_SEP})\d{{3}}{_SEP}?\d{{3}}"
    rf"|(?<!\d{_SP})(?:\(0\d{{3}}\){_SP}?|0\d{{3}}{_SEP})\d{{3}}{_SEP}?\d{{4}}"
    rf"|(?<!\d{_SP})(?:\(0\d{{2}}\){_SP}?|0\d{{2}}{_SEP})\d{{4}}{_SEP}?\d{{4}}"
)
_LABEL_TAIL = rf"\b\.?(?:{_SP}*(?:no\b\.?|number\b|#|details\b))?(?:{_SP}|[:#.])*"
# D-747: a word that only names a phone takes a number written any way; a word that is often something else (call,
# contact, home, T:) takes one written as a phone: a separator in seven digits, an area code in ten
_STRONG_WORDS = r"tel(?:ephone)?|phone|ph|mobile|mob|cell(?:phone)?|fax|pager|landline|helpline"
_STRONG_LABEL = rf"(?i:\b(?:{_STRONG_WORDS})){_LABEL_TAIL}"
_WEAK_LABEL = rf"(?:(?i:\b(?:contact|call|dial|home|number\s+is))|\b[TM](?=\s*:)){_LABEL_TAIL}"
_EN_PHONE_END = rf"(?![\dA-Za-z])(?!{_DASH}\d)"
_STRONG_VALUE = rf"(?:{_EN_PHONE_FULL}|0\d{{9,10}}|\d{{10}}|\d{{3}}{_SEP}?\d{{4}})"
_WEAK_VALUE = rf"(?:{_EN_PHONE_FULL}|[2-9]\d{{9}}|\d{{3}}{_SEP}\d{{4}})"
EN_PHONE = re.compile(
    # the word, then a number of the kind that word takes (each checked ahead); group ``v`` is the number alone
    rf"(?:{_STRONG_LABEL}(?={_STRONG_VALUE}{_EN_PHONE_END})|{_WEAK_LABEL}(?={_WEAK_VALUE}{_EN_PHONE_END}))"
    rf"(?P<v>{_STRONG_VALUE}|{_WEAK_VALUE}){_EN_PHONE_END}"
    rf"|(?<![A-Za-z0-9+.,])(?:{_EN_PHONE_FULL}){_EN_PHONE_END}"  # not inside a code (3D046 0000 019)
)
# NEW-B-44 (D-745): a date of birth, a postal address, a chart number after any of its labels and an email address.
# The owner's run of ``mask_note`` on a month of real notes (counts only) found the first three surviving; the masker
# had no email form either. One definition each for the note masker and the guard service's recognisers (which name
# them, not a copy). Group ``v``: the value; the label stays.
_CJK_A = "一-鿿"
_KANA_A = "぀-ヿ"
_D = "[0-9０-９]"  # a digit, half- or full-width
_ZH_NUM = "[一二三四五六七八九十〇零]"
_NUM_A = r"[0-9０-９一二三四五六七八九十]+"
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
# a date of birth's value: the guard's forms (D-215) and, after a label or before the word for born: 年月日 with spaces
# or full-width digits, 西元 and 民國 (in figures or in Chinese numerals), the ROC year without 民國, an era and its
# abbreviation (S31.3.14), day or month first with a two- or four-digit year, the month's name before or after the day
_DOB_VALUE = (
    rf"{dates.DOB_SPAN}"
    rf"|(?:西元|民國)?\s?{_D}{{2,4}}\s?年\s?{_D}{{1,2}}\s?月\s?{_D}{{1,2}}\s?日"
    rf"|民國{_ZH_NUM}{{1,4}}年{_ZH_NUM}{{1,3}}月{_ZH_NUM}{{1,3}}日"
    rf"|(?:明治|大正|昭和|平成|令和|[MTSHR])\s?(?:{_D}{{1,2}}|元)[年./]\s?{_D}{{1,2}}[月./]\s?{_D}{{1,2}}日?"
    rf"|{_D}{{2,4}}[/.\-／]{_D}{{1,2}}[/.\-／]{_D}{{1,2}}"
    rf"|{_D}{{1,2}}[/.\-]{_D}{{1,2}}[/.\-](?:(?:19|20)\d{{2}}|\d{{2}})"
    rf"|\d{{1,2}}[ -]{_MON},?[ -](?:19|20)\d{{2}}|{_MON} \d{{1,2}},? (?:19|20)\d{{2}}"
)
_DOB_LABEL = (
    r"(?:出生日期|出生年月日|出生日|出生|生日|生年月日|誕生日"
    r"|(?i:\bd\.?o\.?b\b\.?|\bdate\s+of\s+birth\b|\bbirth\s*date\b|\bborn(?:\s+on)?\b))[\s:：]*"
)
# after a label also a compact date (19560314, the ROC 0450314 of a hospital system's header)
DOB_LABELLED = re.compile(rf"{_DOB_LABEL}(?P<v>{_DOB_VALUE}|(?:19|20)\d{{6}}|0?\d{{2}}[01]\d[0-3]\d)(?![0-9])")
# a date followed by the word for born: 生 only at the end of the phrase (1956年3月14日生，), 生まれ, 出生;
# never the 生 of 生検, 生体, 生病, 生長, 生效 and the like
DOB_BORN = re.compile(rf"(?<![0-9])(?P<v>{_DOB_VALUE})\s?(?=生まれ|に生まれ|出生|生(?:$|[\s，,。、;；)）\]】]))")
_AS = r"[^\S\n]?"  # D-756: a space (half or full width) records put between an address's parts
_ZH_NO = (
    rf"{_NUM_A}{_AS}(?:[-－之]{_NUM_A})?{_AS}號(?:之{_NUM_A})?(?:{_AS}{_NUM_A}{_AS}(?:樓|[Ff](?![A-Za-z]))(?:之{_NUM_A})?)?"
    rf"(?:{_AS}{_NUM_A}室)?"
)
ADDRESS_ZH = re.compile(
    rf"(?:[{_CJK_A}]{{1,3}}(?:縣|市))?(?:[{_CJK_A}]{{1,3}}(?:區|鄉|鎮|市))?(?:[{_CJK_A}]{{1,4}}(?:村|里){_NUM_A}鄰)?"
    rf"[{_CJK_A}]{{1,5}}(?:路|街|大道){_AS}(?:{_NUM_A}{_AS}段{_AS})?(?:{_NUM_A}{_AS}巷{_AS})?(?:{_NUM_A}{_AS}弄{_AS})?{_ZH_NO}"
    # a village's address with no road: county, township, village and 鄰, number
    rf"|(?:[{_CJK_A}]{{1,3}}(?:縣|市))?[{_CJK_A}]{{1,3}}(?:鄉|鎮|區|市)[{_CJK_A}]{{1,4}}(?:村|里){_NUM_A}鄰{_ZH_NO}"
)
ADDRESS_JA = re.compile(
    rf"(?:東京都|北海道|大阪府|京都府|[{_CJK_A}]{{2,3}}県)[{_CJK_A}{_KANA_A}]{{1,10}}?(?:市|区|町|村|郡)"
    rf"[{_CJK_A}{_KANA_A}]{{0,8}}?[0-9０-９]+(?:(?:丁目|番地?|号|[-－ー]|の)[0-9０-９]*){{1,4}}"
    rf"(?:\s?[0-9０-９]+号室)?"
)
# a number, one to three capitalised words that are not a unit or a count, a street of a known type, then a flat, a
# town, a state or province and a ZIP code or a British postcode; never a year before it
_EN_WORD = r"(?!(?:Units?|Mg|Mcg|Weeks?|Days?|Hours?|Times?|Doses?|Tablets?|Caps?|Post|Op|Daily|Dose)\b)[A-Z][a-z]+"
ADDRESS_EN = re.compile(
    rf"\b(?!(?:19|20)\d{{2}}\b)\d{{1,5}}[A-Z]?\s+(?:{_EN_WORD}\s+){{1,3}}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Boulevard|Blvd|Drive|Dr|Way|Close|Court|Ct"
    r"|Place|Pl|Crescent|Terrace|Square|Sq|Parade|Highway|Hwy|Circle|Gardens|Row|Mews|Grove)\b\.?"
    r"(?:,\s*(?:Apt\.?|Unit|Suite)\s*\d+)?(?:,\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)?"
    r"(?:,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?|\s+[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}|,\s*[A-Z]{2}\b(?![a-z]))?"
    r"(?=\s*(?:[,.;:)]|$)|\s+[a-z])"
)
# whatever follows an address label, to the end of the field: punctuation, a line break, a tab, two spaces or the
# next field's label (診斷:, Diagnosis:); its first word holds a figure or a word of an address (市, 路, 號, 丁目).
# A Chinese or Japanese label takes a separator; an English one is "Address:" (capital, or after home, postal,
# mailing, current, permanent): "to address: the renal dose" is no label
_FIELD_END = r"(?=[，,。；;\n\t　]|\s{2}|\s+[^\s:：，,。]{1,12}[:：]|\s*$)"
ADDRESS_LABELLED = re.compile(
    r"(?:(?:通訊地址|戶籍地址|居住地址|聯絡地址|住址|地址|戶籍地|居住地|現住所|住所|居所|現住)[\s:：]+"
    r"|(?<![入居現同])住[:：]\s*"  # never 入住: (admitted to)
    r"|(?:\b(?:[Hh]ome|[Pp]ostal|[Mm]ailing|[Cc]urrent|[Pp]ermanent)\s+address|\bAddress|\bADDRESS|\bAddr\.)\s*[:：]\s*)"
    rf"(?P<v>(?=[^\s，,。；;\n　]{{0,30}}?(?:[0-9０-９]|[市縣區鄉鎮村里路街號町都道府県丁番]))"
    rf"[^\s，,。；;、\n（(：:][^，,。；;\n\t　]{{1,60}}?){_FIELD_END}"
)
# NEW-B-50 (D-756): a labelled value as records write it: letters (either case) and digits, full-width too, groups
# joined by - _ / . or by a space (a group after a space holds a digit); four digits or more, found by a bounded
# look ahead (a look that ran to the line's end made a long line slow)
_LABELLED_VALUE = (
    r"(?=(?:[^0-9０-９\n，,。；;、]{0,8}[0-9０-９]){4})"
    r"[A-Za-z0-9０-９]+(?:[-_/.－][A-Za-z0-9０-９]+|[^\S\n][A-Za-z0-9０-９]*[0-9０-９][A-Za-z0-9０-９]*)*"
)
# a chart number after its label, the labels of Taiwanese, Japanese and English records, the label against the number
# too, written against it; full-width digits; the number holds four figures or more (never D-143, a decision's)
MRN_LABELLED = re.compile(
    r"(?:病歷號(?:碼)?(?:為|是)?|病歷編號|病歷碼|病歷No\.?|病历号|病例號(?:碼)?|病歴番号|住院號(?:碼)?|門診號(?:碼)?"
    r"|病人編號|歸檔號|カルテ(?:番号|No\.?)|患者(?:ID|番号|No\.?)|診察券番号|病[人患]ID"
    r"|(?i:(?<![A-Za-z])MRN|(?<![A-Za-z])chart\s*(?:no\.?|number|\#)|\bmedical record (?:no\b\.?|number\b)"
    r"|\bhospital\s*(?:no\b\.?|number\b)|\badmission\s*no\b\.?|\bvisit\s*no\b\.?|\bpatient\s*ID\b|\binsurance\s*ID\b)|(?<![A-Za-z])ID\s*[:：](?:\s*No\.?)?)"
    r"[\s:：#（(\[［【]*(?P<v>" + _LABELLED_VALUE + r")(?![A-Za-z0-9０-９])"
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# NEW-B-50 (D-756): shapes the note masker missed and the guard had, or neither had. One definition each, read by the
# masker (:func:`note_spans`) and the guard service's recognisers (the guard also reads every span the masker finds).
# Group ``v``: the value (the word stays). Every look ahead is bounded: a note can be one long line.
# A resident certificate (ARC) number, the new format (a letter, 8 or 9, eight digits) and the old (two letters,
# eight digits), a space after the letter allowed; masked whatever its check digit (the guard validates it to name it)
TW_ARC = re.compile(r"(?<![A-Za-z0-9])[A-Z] ?(?:[89]\d{8}|[A-D]\d{8})(?![0-9])")
# twelve digits, together or in fours (joined by a space, a dash, a dot or a slash): the shape of a health-insurance
# card number and of a My Number. The guard takes every one (:data:`TWELVE_DIGITS_ANY`); the masker leaves three clock
# times in a row (a medication schedule written in four-digit times), and masks them too after a card's word
_TWELVE = r"\d{4}[ \-./]?\d{4}[ \-./]?\d{4}"
TWELVE_DIGITS_ANY = re.compile(rf"(?<![\d\-./]){_TWELVE}(?![\d\-./]?\d)")
_HHMM = r"(?:[01]\d|2[0-3])[0-5]\d"
TWELVE_DIGITS = re.compile(
    rf"(?<![\d\-./])(?!{_HHMM}[^\S\n]{_HHMM}[^\S\n]{_HHMM}(?![\d\-./]?\d)){_TWELVE}(?![\d\-./]?\d)"
)
_ALNUM_W = "A-Za-z0-9０-９Ａ-Ｚａ-ｚ"
_HAS_DIGIT = r"(?=[^\s，,。；;、]{0,10}[0-9０-９])"  # the value (at most 11 characters) holds a digit
_ID_VALUE = rf"{_HAS_DIGIT}[{_ALNUM_W}][{_ALNUM_W}\-－]{{0,9}}"
_COUNT_AFTER = r"(?!\s?[次間個天日週月年張位床被])"  # 病房 2 次, 病室2間: a count, not a room
# a bed number after its word (床號, 病床, 床位, 床:, bed no.)
BED_LABELLED = re.compile(
    rf"(?:床號(?:碼)?|床号|病床(?:號碼|號)?|床位(?:號碼|號)?|床次|床(?=[\s:：#])|(?i:\bbed\b\.?\s*(?:no\b\.?|number\b|#)?))"
    rf"[\s:：#]*(?:No\.?\s*)?(?P<v>{_ID_VALUE}){_COUNT_AFTER}"
)
# a bed number written against 床 (12床, 5B-12床, A3床, ３床, 12號床); never a count of beds (共有20床, 2床被, 50床病房)
BED_NUMBER = re.compile(
    rf"(?<![{_ALNUM_W}\-－共有約計總])(?P<v>(?=[^床\s]{{0,10}}[0-9０-９])[{_ALNUM_W}]{{1,5}}(?:[-－][{_ALNUM_W}]{{1,5}})?)"
    r"\s?號?床(?!被|位|單|墊|褥|病房|加護|數)"
)
# a room number after its word (病房, 房號, 病室, 室號, 房間) or before it (712病房, 712房, 712室)
ROOM = re.compile(
    rf"(?:病房號?|房號|房号|病室|室號|房間|病室番号)[\s:：#]*(?:No\.?\s*)?(?P<v>{_ID_VALUE}){_COUNT_AFTER}"
)
ROOM_NUMBER = re.compile(
    rf"(?<![{_ALNUM_W}\-－共有約計總第])(?P<v>(?=[{_ALNUM_W}\-－]{{0,7}}[0-9０-９]{{3}})[{_ALNUM_W}][{_ALNUM_W}\-－]{{2,7}})"
    r"(?:病房|房|室)(?![間號])"
)
# a staff member's name beside a role word, the surname in no list: after the role (主治醫師：王大明, 記錄者 林小華,
# 護理師陳美, 醫師(王大明), a list 護理師：王大明、林小華; 2 to 4 characters each, then the end of the name or a verb
# of a note) or before it (王大明醫師, 李護理師, 王大明/護理師; 1 to 3 characters after a boundary). Never the role
# word's own qualifier, a department, a pronoun, a label word or a common verb or noun of a note: those are left.
_NOTE_CJK = "[一-鿿]"
_ROLES = (
    r"主治醫師|住院醫師|總醫師|值班醫師|專科護理師|呼吸治療師|護理長|醫師|醫生|護理師|護士|藥師|個管師|社工師|營養師"
    r"|治療師|心理師|專師|記錄者|紀錄者|記錄人員|(?i:Dr\b\.?|NP\b|RN\b|MD\b)"
)
_ROLE_WORD = rf"(?:{_ROLES})"
_ROLE_AFTER = (
    r"(?:主治醫師|住院醫師|護理長|醫師|醫生|護理師|護士|藥師|個管師|社工師|營養師|治療師|心理師|大夫|教授|主任)"
)
_NOTE_VERBS = (
    r"說明|建議|評估|診視|告知|解釋|同意|指示|處理|交班|開立|表示|診察|看診|回覆|確認|追蹤|協助|陪同|衛教|執行|查房"
    r"|安排|聯絡|通知|給予|予以|囑咐|討論|會同|簽名|簽署|核對|交代|看過|認為|決定|開藥|巡房|解說|發藥|換藥|待查|同上"
    r"|休假|詢問|回報|報告|請示|檢查|抽血|翻身|會診|處置|發現|判斷|觀察|叮嚀|提醒|說|問|請|已|會|將|再|於|在"
)
_NOT_A_NAME = (
    r"(?!主治|住院|值班|總|專科|實習|會診|主責|負責|照會|原|本|該|此|其|主任|個管|營養|臨床|藥劑|呼吸|治療|門診"
    r"|急診|病房|夜班|白班|小夜|大夜|資深|麻醉|家醫|研究|社區|牙|中醫|西醫|群|團隊|護理站|護理|看護|櫃台|空服|鄰居"
    r"|這位|那位|一名|一位|一個|兩位|二位|該名|某位|每位|老|醫師|醫生|護理師|藥師|護士"
    rf"|{_NOTE_VERBS}"
    r"|並|及|與|和|或|等|們|以|之|的|為|又|有|無|未|不|經|由|向|對|跟|給|後|前|時|可|要|需|能|均|皆|亦|也"
    r"|即|則|就|才|還|仍|另|僅|只|共|各|每|某|您|你|我|他|她|家屬|家属|案|病人|病患|患者|個案|受試者|聯絡人)"
)
_NAME_CHAR = rf"(?:(?![及和與或並等的之於在為由向對給請經、，,。]){_NOTE_CJK})"
_STAFF = rf"{_NOT_A_NAME}{_NAME_CHAR}{{2,4}}?"
_NAME_END = rf"(?=[\s，,。、;；:：)）\]】/0-9０-９]|$|{_ROLE_AFTER}|{_NOTE_VERBS})"
STAFF_NAME_AFTER = re.compile(
    rf"{_ROLE_WORD}[\s:：(（/]*(?P<v>{_STAFF}{_NAME_END}(?:[、/,，及和與][\s　]*{_STAFF}{_NAME_END})*)"
)
_BOUNDARY = r"(?:^|(?<=[\s，,。、;；:：(（「『\[【/])|(?<=[由經請與和及跟向對給為屬同知]))"
STAFF_NAME_BEFORE = re.compile(
    rf"{_BOUNDARY}{_NOT_A_NAME}(?P<v>{_NAME_CHAR}{{1,3}}?)(?<![科部室組院所處])(?<!中心)[\s/]?{_ROLE_AFTER}"
)
# a name before an honorific or a kinship word said of an elder (王先生, 陳美華小姐, 林阿嬤, 陳伯伯), the surname in no
# list: after a boundary, 1 to 3 characters, never a pronoun, a count or a word of a note before it (其先生, 一位女士)
NAME_HONORIFIC = re.compile(
    rf"{_BOUNDARY}{_NOT_A_NAME}(?P<v>{_NAME_CHAR}{{1,3}}?)\s?"
    r"(?:先生|小姐|女士|太太|老先生|老太太|阿嬤|阿公|伯伯|伯母|奶奶|爺爺|媽媽|叔叔|阿姨|婆婆|阿伯)"
)
# an insurance, identity or resident certificate number after its label (the wider labelled value)
ID_LABELLED = re.compile(
    r"(?:健保卡號(?:碼)?|健保卡|健保號碼|身分證(?:字號|號碼)?|身份證(?:字號|號碼)?|居留證(?:號碼|統一證號)?|統一證號"
    r"|保険者番号|被保険者番号|個人番号|マイナンバー|(?i:insurance\s*no\.?|ID\s*no\.?|ARC\s*(?:no\.?|number)?))"
    r"[\s:：#\[［【(（]*(?P<v>" + _LABELLED_VALUE + r")(?![A-Za-z0-9０-９])"
)
# a phone number after its word, written as records write it (spaces, dots, dashes, brackets, an extension); never a
# date written after the word (電話：2026-11-15 已聯絡)
PHONE_LABELLED = re.compile(
    r"(?:聯絡電話|連絡電話|聯絡人電話|電話號碼|電話|手機號碼|手機|行動電話|市話|家用電話|公司電話|電話番号|携帯(?:電話)?"
    r"|(?i:\btel(?:ephone)?\b\.?|\bphone\b|\bmobile\b))[\s:：#]*"
    rf"(?!{_DATE_AFTER})"
    r"(?P<v>(?=(?:[^0-9０-９\n]{0,3}[0-9０-９]){7})[+＋(（\[［]?[0-9０-９]"
    r"[0-9０-９ \-－–—.()（）\[\]［］]{5,22}[0-9０-９]"
    r"(?:\s?(?:#|轉|分機|內線|(?i:ext)\.?)\s?[0-9０-９]{1,6})?)"
)

DATE = dates.PHI_SPAN  # Gregorian and 民國 written out (D-215: the pattern lives in tb_common.dates, unchanged)
EN_NAME = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?|\bPatient(?: name)?:\s*[A-Z][a-z]+\s+[A-Z][a-z]+"
)


@dataclass(frozen=True)
class PhiClearance:
    """Proof that ``text_sha`` was scanned clean. Only :func:`scan` creates these."""

    text_sha: str


@dataclass
class PhiScan:
    hit: bool
    findings: list[tuple[str, str]] = field(default_factory=list)  # (kind, masked snippet)
    clearance: PhiClearance | None = None


def _mask(s: str) -> str:
    return s[0] + "*" * (len(s) - 1) if s else s


def _cjk_names(text: str) -> list[str]:
    hits: list[str] = []
    surname = "|".join(sorted(ROC_COMPOUND, key=len, reverse=True)) + "|[" + "".join(sorted(ROC_SURNAMES)) + "]"
    given = r"[一-鿿]{1,2}"
    pats = [
        rf"(?:{surname}){given}\s?{HONORIFIC}",
        rf"{PATIENT_WORD}[：:\s]?(?:{surname}){given}(?=[，,、\s(（]|$)",
        rf"(?:{surname}){given}[，,、\s]*[（(]?(?:男|女)[)）]?[，,、\s]*\d{{1,3}}\s?歲",
    ]
    for p in pats:
        hits.extend(m.group(0) for m in re.finditer(p, text))
    jp = "|".join(sorted(JP_SURNAMES, key=len, reverse=True))
    hits.extend(m.group(0) for m in re.finditer(rf"(?:{jp})[一-鿿぀-ヿ]{{0,3}}{HONORIFIC}", text))
    return hits


def variables_text(variables: Any) -> str:
    """The dynamic content of a prompt: every scalar value of its variables (keys sorted, list order kept), one per
    line, unescaped — what :func:`scan` must clear before a call may leave the box. The prompt templates around it
    are fixed, reviewed text; a JSON dump would not do (``\\n`` escapes hide an MRN at the start of a line)."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k in sorted(v, key=str):
                walk(v[k])
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)
        elif v is not None:
            out.append(str(v))

    walk(variables)
    return "\n".join(out)


def scan(text: str, mrn_regex: str | None = None) -> PhiScan:
    findings: list[tuple[str, str]] = []
    for m in TW_ID.finditer(text):
        findings.append(("taiwan_id", _mask(m.group(0))))
    if mrn_regex:
        body = mrn_regex.strip("^$")
        for m in re.finditer(rf"(?<![0-9A-Za-z\-/.]){body}(?![0-9A-Za-z\-/.])", text):
            findings.append(("mrn", _mask(m.group(0))))
    for m in PHONE.finditer(text):
        findings.append(("phone", _mask(m.group(0))))
    for m in EN_PHONE.finditer(text):
        findings.append(("phone", _mask(m.group("v") or m.group(0))))
    for m in KEYWORDS.finditer(text):
        findings.append(("keyword", m.group(0)))
    names = _cjk_names(text)
    findings.extend(("name", _mask(n)) for n in names)
    for m in EN_NAME.finditer(text):
        findings.append(("name", _mask(m.group(0))))
    # date of birth near a name-like token
    for m in DATE.finditer(text):
        window = text[max(0, m.start() - 30) : m.end() + 30]
        if _cjk_names(window) or EN_NAME.search(window) or re.search(r"生日|出生|DOB|born", window, re.I):
            findings.append(("dob_near_name", _mask(m.group(0))))
    # 10C-1: every span the note masker masks (note_spans), so what would be masked in a note never reaches a model
    # unmasked either: a Japanese name, insurance number or address, a phone in full-width figures, a My Number
    findings.extend((_SCAN_KIND.get(kind, kind), _mask(text[s:e])) for kind, s, e in note_spans(text))
    if findings:
        return PhiScan(True, findings, None)
    return PhiScan(False, [], PhiClearance(sha256_text(text)))


# ------------------------------------------------------------------------------------------------ note text (T-600)
# FR-DEID-01 (CR-028, DATA-020): names, phone numbers, chart numbers and ID numbers in note text are masked before
# the text is chunked, indexed for full-text search or embedded. The lake's ``document`` table keeps the original
# under the ``phi`` label (D-337). Masking keeps the length: every character of a span other than white space becomes
# ``MASK_CHAR``, so chunk boundaries, offsets and line breaks stay where they were and the clinical words around a span
# are untouched. ``○`` is how Taiwanese and Japanese records mask a name by hand; the tokenizer drops it, so a masked
# span gives no token to the full-text index or the hash embedder.
MASK_CHAR = "○"
# recorded in lake_meta.note_mask; bump when the recognisers below change what they mask (2: English phones, D-744;
# 3: dates of birth, addresses and chart labels, D-745; 4: ARC, 12-digit, bed and room numbers, staff and honorific
# names without a listed surname, wider labelled values, D-756; 5: full addresses with spaces, D-756; 6: English
# Taiwan charts, romanised and Han names after English words and the English form of an address, D-923; 7: Japanese
# names in kana and old-form kanji, insurance 記号・番号・枝番, 公費 and 受給者 numbers, Japanese phones, postal codes,
# era dates of birth and city addresses, 10C-1)
NOTE_MASK_VERSION = "7"

_CJK_N = "一-鿿"
_KANA_N = "぀-ヿ"
_ROC = "|".join(sorted(ROC_COMPOUND, key=len, reverse=True)) + "|[" + "".join(sorted(ROC_SURNAMES)) + "]"
_JP = "|".join(sorted(JP_SURNAMES, key=len, reverse=True))
_GIVEN_JP = rf"(?:(?!さん|様|くん|ちゃん|より|から)[{_CJK_N}{_KANA_N}])"  # a given name, not the honorific after it
_ROLE_ZH = r"(?:醫師|醫生|護理師|藥師|個管師)"
# D-756: a pattern that ends at a fixed word is run only in a window around each such word (its anchor): pattern
# id -> (the anchor, characters before it, characters after it). A match always holds its anchor and lies inside
# those bounds, so the windows give the spans the whole note gives (the tests compare the two).
_ROLE_ANCHOR = re.compile(
    r"主治醫師|住院醫師|護理長|醫師|醫生|護理師|護士|藥師|個管師|社工師|營養師|治療師|心理師|大夫|教授|主任"
)
_HONORIFIC_ANCHOR = re.compile(
    r"老先生|老太太|先生|小姐|女士|太太|阿嬤|阿公|伯伯|伯母|奶奶|爺爺|媽媽|叔叔|阿姨|婆婆|阿伯|君|さん|様|氏|くん|ちゃん"
)
_NOTE_WINDOWS: dict[int, tuple[re.Pattern[str], int, int, bool]] = {}


def _windowed(
    rx: re.Pattern[str], anchor: re.Pattern[str], before: int, after: int, to_line_end: bool = True
) -> re.Pattern[str]:
    """``to_line_end``: the window runs on to its line's end (a pattern with a look ahead); False for a pattern with
    none, whose window then ends ``after`` characters past the anchor (NEW-B-51: a long line stays one pass)."""
    _NOTE_WINDOWS[id(rx)] = (anchor, before, after, to_line_end)
    return rx


def _finditer(rx: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """``rx.finditer(text)``, or for a windowed pattern its matches in the window around each anchor (overlapping
    windows joined; a window runs on to its line's end, so a look ahead reads what it would in the whole note)."""
    win = _NOTE_WINDOWS.get(id(rx))
    if win is None:
        yield from rx.finditer(text)
        return
    anchor, before, after, to_line_end = win
    spans: list[list[int]] = []
    line_end = -1  # the end of the line the last window ran to: each line's end is looked for once (10C-1: a line of
    # a hundred thousand anchors looked for it once per anchor, quadratic time)
    for a in anchor.finditer(text):
        lo, hi = max(0, a.start() - before), min(len(text), a.end() + after)
        if to_line_end:
            if hi > line_end:
                end = text.find("\n", hi)
                line_end = len(text) if end < 0 else end
            hi = line_end
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    for lo, hi in spans:
        yield from rx.finditer(text, lo, hi)


# NEW-B-55 (D-923): English Taiwan charts (D-1037's check). A Latin name word may be hyphenated (Mei-Ling,
# Ellison-Ward) or start O' (O'Neil); a name is up to three words (and an initial). Every quantifier below is bounded:
# the masking review's rule (no shape may take time that grows faster than the note)
_EN_NAME_WORD = r"(?:Ma?c|O')?[A-Z][a-z]{1,30}(?:-[A-Za-z][a-z]{1,30}){0,2}"
_EN_NAME = (
    rf"(?:[A-Z]\.[ \t]{{1,3}})?{_EN_NAME_WORD}"
    rf"(?:,[ \t]?{_EN_NAME_WORD}|(?:[ \t]{{1,3}}[A-Z]\.)?(?:[ \t]{{1,3}}{_EN_NAME_WORD}){{0,2}})"
)
# capitals after a label take the record's own form only, surname, comma, given name (SMITH, JOHN; CHEN, MEI-LING):
# two capital words without the comma are as often an abbreviation list (PATIENT: NPO AFTER MIDNIGHT, HTN, DM)
_EN_NAME_CAPS = r"(?:[A-Z]')?[A-Z]{2,20}(?:-[A-Z]{2,20})?,[ \t]?[A-Z]{3,20}(?:[- ][A-Z]{2,20})?\b"
#: the surnames of Taiwan as passports and charts romanise them (Wade-Giles), and in pinyin; compound ones joined
_ROC_LATIN_WORDS = (
    "Bai Bao Bian Cai Cang Cao Chang Chao Chen Cheng Chi Chiang Chiao Chien Chin Chiu Chou Chu Chuang Chung "
    "Cui Dai Deng Ding Dong Du Fan Fang Fu Gao Gong Guan Guo He Ho Hong Hou Hsia Hsiao Hsieh Hsing Hsiung Hsu "
    "Hsueh Hu Huang Hung Jen Ji Jian Jiang Kan Kang Kao Ke Ko Kuan Kung Kuo Lai Lan Lee Li Lian Liang Liao "
    "Lien Lin Liu Lo Lu Lung Luo Lyu Ma Mao Mei Meng Miao Nie Nieh Ou Pai Pan Pao Peng Pien Qiao Qin Qiu Ren "
    "Shao Shen Shih Shi Song Su Sun Sung Tan Tang Tao Teng Tian Tien Ting Tong Tsai Tsao Tsang Tseng Tsou "
    "Tsui Tu Tung Wan Wang Wei Wen Weng Wu Xia Xiao Xie Xing Xiong Xu Xue Yang Yao Yeh Ye Yen Yan Yin Yu Yuan "
    "Yueh Yue Zeng Zhang Zhao Zheng Zhong Zhou Zhu Zhuang Zou Ou-Yang Ouyang Szu-Ma Sima Chang-Chien Chu-Ko "
    "Zhuge Shang-Kuan Shangguan "
    # the spellings of Taiwan's passports (MOFA's tongyong and its own Wade-Giles forms)
    "Jhang Jheng Jhou Jhuang Jhu Jhong Syu Syue Shieh Shiu Shiau Chiou Jao Jau Jou Chuo Tsay Hsü Hsiu Jian Jiou"
)
ROC_SURNAMES_LATIN = tuple(_ROC_LATIN_WORDS.split())
_ROC_LATIN = "|".join(sorted(ROC_SURNAMES_LATIN, key=len, reverse=True))
_ROC_LATIN_CAPS = "|".join(sorted((x.upper() for x in ROC_SURNAMES_LATIN), key=len, reverse=True))
# one syllable of romanised Mandarin (Wade-Giles or pinyin): an initial, one to three vowels, a final n, ng, h or r.
# An English word is rarely two of them (Self, Harmed, Signed, Morbid are none), a given name is (Mei-Ling, Meiling)
_SYL = (
    r"(?:[Cc][Hh][Hh]?|[Hh][Ss]|[Tt][SsZz]|[Ss][HhZzSs]|[Zz][Hh]|[Jj][Hh]|[Kk][Ww]|[Hh][Ww]"
    r"|[BbPpMmFfDdTtNnLlGgKkHhJjQqXxRrZzCcSsYyWw])?"
    r"[AaEeIiOoUuÜü]{1,3}(?:[Nn][Gg]|[Nn]|[Rr][Hh]|[Hh]|[Rr])?"
)
# a given name of two syllables: joined by a hyphen or an apostrophe (as Taiwan writes it: Mei-Ling, MEI-LING), or
# in any way where a label or the record's comma says a name is there (Meiling, Mei Ling, M.L.)
_GIVEN_JOINED = rf"(?:(?=[A-Z][a-z]){_SYL}[-'’](?=[A-Za-z]){_SYL}|(?=[A-Z]{{2}}){_SYL}-{_SYL}|[A-Z]\.[ \t]?-?[A-Z]\.)"
_GIVEN_ANY = (
    rf"(?:(?=[A-Z][a-z]){_SYL}(?:[-'’]|[ \t])?(?<=[-'’ \ta-z]){_SYL}|(?=[A-Z]{{2}}){_SYL}(?:-|[ \t])?{_SYL}"
    r"|[A-Z]\.[ \t]?-?[A-Z]\.)"
)
_ROC_ANY = rf"(?:{_ROC_LATIN}|{_ROC_LATIN_CAPS})"
_SURNAMES = rf"{_ROC_ANY}(?:[ \t]{_ROC_ANY})?"  # a married woman's two surnames (陳林美玲: Chen Lin Mei-Ling)
# a Taiwanese name in Latin letters with no label: a surname of the list (or two) and a given name, joined as
# Taiwan writes it (Chen Mei-Ling, Mei-Ling Chen, CHEN MEI-LING, Chen Lin Mei-Ling) or after the record's comma
# (CHEN, MEI LING; Chen, Meiling); a possessive after it is left (Chen Mei-Ling's son). With no label, no comma and
# no hyphen the rule does not read a name (Chen Meiling): two capitalised words of a chart are too often a finding
# (Lung Cancer, Pan Neuro, He Tender) - the second review counted 37 % of header words as two syllables
# romanised words of medicine and practice that read as a surname and a given name: never a name
_NOT_ROMANISED = (
    r"(?!(?i:ma[ \t-]?huang|tai[ \t-]?chi|qi[ \t-]?gong|chi[ \t-]?kung|dong[ \t-]?quai|kung[ \t-]?fu"
    r"|he[ \t-]?shou[ \t-]?wu|ho[ \t-]?chi[ \t-]?minh|lo[ \t-]?han)\b)"
)
ROMANISED_TW_NAME = re.compile(
    rf"(?<![-'A-Za-z]){_NOT_ROMANISED}"
    rf"(?P<v>{_SURNAMES}[ \t]{{1,2}}{_GIVEN_JOINED}|{_SURNAMES},[ \t]?{_GIVEN_ANY}"
    rf"|{_GIVEN_JOINED}[ \t]{{1,2}}{_ROC_ANY})"
    r"(?![A-Za-z0-9])(?!-|'(?!s\b))"
)
# a Han name after an English label with its colon, a word for a relative or a staff word (Name: 黃家豪, son 曾冠宇,
# Wife (陳美玲), VS 林建宏): a surname of the list and one or two characters (a space after the surname allowed), the
# end of the Han run after it; a second name after the first is masked too. Never after a bare "Patient" or "by"
# (Patient 高血壓, Referred by 林口): the label words are what says a name follows
_HAN_NAME = rf"(?:{_ROC})[ 　]?[{_CJK_N}](?:[ 　]?[{_CJK_N}])?(?![{_CJK_N}])"
NAME_HAN_AFTER_EN = re.compile(
    r"(?:\b(?:[Nn]ame|NAME|[Pp]atient(?: [Nn]ame)?|PATIENT|[Ii]nformant|[Aa]ttending|[Cc]aregiver|[Gg]uardian"
    r"|[Cc]ontact(?: [Pp]erson)?|[Ff]amily|[Nn]ext of [Kk]in|NOK|[Ss]igned(?: by)?|Pt|PT|[Pp]hysician"
    r"|[Aa]ttending [Pp]hysician|[Pp]rimary [Nn]urse|[Nn]urse|[Rr]esident)[ \t]{0,3}[:：][ \t]{0,3}"
    r"|\b(?:[Dd]aughter|[Ss]on|[Ww]ife|[Hh]usband|[Mm]other|[Ff]ather|[Ss]ister|[Bb]rother|[Ss]pouse|[Pp]artner"
    r"|[Rr]elative|[Gg]randson|[Gg]randdaughter|[Nn]urse|[Rr]esident|[Pp]hysician|VS|R[1-5]|NSP|NP|PGY[1-3]?|Dr\.?)"
    r"(?:-in-law)?[ \t]{0,3}[(（,:：]?[ \t]{0,3})"
    rf"(?P<v>{_HAN_NAME}(?:[ \t]{{0,3}}[、,，/][ \t]{{0,3}}{_HAN_NAME}|[ \t]{{1,3}}{_HAN_NAME}){{0,4}})"
)
# a Taiwan address in its English form, as the post office and the charts write it (Rm. 2, 13F., No. 322, Ln. 20,
# Sec. 4, Minsheng E. Rd. Sec. 4, Xinyi Vil., Da'an Dist., Taipei City 106): parts joined by a comma or a space, a
# road or a village, district or township after the number, then any of the parts again. Run only around each "No"
# and a number; every part is bounded, so no match is longer than ADDRESS_TW_EN_MAX (the window's reach)
_TW_W = r"[A-Z0-9][A-Za-z0-9'’\-]{0,24}\.?"
_TW_SEP = r"(?:,[ \t]{0,2}\n?[ \t]{0,2}|[ \t]{1,2}\n?[ \t]{0,2}|\n[ \t]{0,2})"
_TW_CITY = (
    r"(?:New[ \t])?(?:Taipei|Taoyuan|Taichung|Tainan|Kaohsiung|Keelung|Hsinchu|Chiayi|Miaoli|Changhua|Nantou"
    r"|Yunlin|Pingtung|Yilan|Hualien|Taitung|Penghu|Kinmen|Lienchiang|Matsu)(?:[ \t](?:City|County))?\b"
    r"|Taiwan(?:[ \t]\(?R\.?O\.?C\.?\)?)?"
)
_TW_NUMBERED = (
    r"(?:(?:Ln|Lane|Aly|Alley|Sec|Section|Neighborhood|Nbhd|Lin)\.?[ \t]?\d{1,4}"
    r"|\d{1,3}(?:st|nd|rd|th)[ \t](?:Neighborhood|Nbhd|Lin)\.?)"
)
_TW_FLOOR = r"(?:\d{1,3}(?:F|st|nd|rd|th)\.?(?:[ \t]?(?:Fl|Floor)\.?)?(?:-\d{1,2})?|(?:Fl|Floor)\.?[ \t]?\d{1,3})\b\.?"
_TW_ROAD = (
    rf"(?:{_TW_W}[ \t]){{1,4}}?(?:Rd|Road|St|Street|Ave|Avenue|Blvd|Boulevard|Expy|Hwy)\b\.?"
    r"(?:[ \t](?:Sec|Section)\.?[ \t]?\d{1,2})?"
)
_TW_AREA = rf"(?:{_TW_W}[ \t]){{0,3}}?{_TW_W}[ \t]?(?:Dist|District|Township|Twp|Town|Vil|Village|City|County)\b\.?"
_TW_BARE = rf"[A-Z][a-z'\-]{{1,24}}(?=,[ \t]?{_TW_CITY})"  # a district written bare before its city (Banqiao, ...)
ADDRESS_TW_EN = re.compile(
    r"(?:\b(?:Rm|Room)\.?[ \t]?\d{1,4}[A-Z]?,[ \t]?)?"
    r"(?:\b\d{1,3}(?:F|st|nd|rd|th)\.?(?:[ \t]?(?:Fl|Floor)\.?)?(?:-\d{1,2})?,?[ \t]?)?"
    r"\bNo\.?[ \t]?\d{1,5}(?:-\d{1,4})?"
    rf"(?:{_TW_SEP}(?:{_TW_NUMBERED}|{_TW_FLOOR})){{0,5}}"
    rf"{_TW_SEP}(?:{_TW_ROAD}|{_TW_AREA})"
    rf"(?:{_TW_SEP}(?:{_TW_NUMBERED}|{_TW_FLOOR}|{_TW_CITY}|{_TW_ROAD}|{_TW_AREA}|{_TW_BARE}|\d{{3,6}}\b)){{0,6}}"
)
# the same address in the Chinese order, written in English (Taipei City Da'an District Heping E. Rd. Sec. 1 No. 18
# 5F; Jianguo Rd. No. 18): the city or the area first, then the road, its parts and the number last
ADDRESS_TW_EN_CN_ORDER = re.compile(
    rf"(?:(?:{_TW_CITY}|{_TW_AREA}){_TW_SEP}){{0,3}}{_TW_ROAD}(?:{_TW_SEP}{_TW_NUMBERED}){{0,5}}"
    rf"{_TW_SEP}?\bNo\.?[ \t]?\d{{1,5}}(?:-\d{{1,4}})?\b(?:{_TW_SEP}{_TW_FLOOR})?"
)
#: the longest text ADDRESS_TW_EN can match after its anchor, and before it (the window's reach; a test checks it)
ADDRESS_TW_EN_MAX, ADDRESS_TW_EN_BEFORE = 1600, 40

# 10C-1 (plan 10, F3; review 11 JP-8): Japanese identifiers the rules above let through. The review's synthetic lines
# kept a name in katakana (full- or half-width), a name in old-form kanji (髙, 﨑, 齋, 邊) before さん or 様, and the
# health-insurance 記号 and 番号 unmasked; the probe set (eval/phi_synth/ja_guard_probes.json) adds 公費 and 受給者
# numbers, labelled and full-width chart labels, Japanese phone and postal forms, era dates of birth and addresses that
# start at the city. The rules key on kana, a Japanese honorific, label or era, or a Japanese number's shape. Two are
# not Japanese-only and change other notes too: a bracketed landline of ten digits (Japan's length; a Taiwanese one of
# ten digits was already masked) and an e-mail written with a full-width ＠. Every quantifier is bounded (a run of
# white space after a label is at most three characters). Group ``v``: the value; the label stays.
_JA_KANJI = "一-鿿々〆ヶ豈-﫿\U00020000-\U0002ffff"  # with the compatibility forms (﨑 U+FA11) and 𠮷
_JA_HIRA = "ぁ-ゖ"
_JA_KATA = "ァ-ヺーｦ-ﾟ"  # full-width katakana and the long mark, half-width katakana and its sound marks
_JS = "[ 　]"  # a space, half or full width
_JA_KANA_WORD = rf"[ァ-ヺｦ-ﾝ][{_JA_KATA}]{{0,11}}"  # never starting with a long mark or a sound mark
_JA_KANA_NAME = rf"{_JA_KANA_WORD}(?:[・･]{_JA_KANA_WORD}|{_JS}{{1,2}}{_JA_KANA_WORD})?"
_JA_HIRA_NAME = rf"[{_JA_HIRA}]{{1,8}}(?:{_JS}{{1,2}}[{_JA_HIRA}]{{1,8}})?"
# the particles a name may run into (山田さんは, 佐藤が実施); any other hiragana after a word makes it a longer word
_JA_PARTICLE = "はがのにをへともでやかよねらたっ"
_JA_END = rf"(?:(?=[{_JA_PARTICLE}])|(?![{_JA_HIRA}]))"  # an end: a particle, or anything but hiragana
_JA_END_HARD = rf"(?:(?=[{_JA_PARTICLE}])|(?![{_JA_HIRA}{_JA_KANJI}]))"  # the same, and no kanji either
# a kanji of a name: never an honorific (美津子様: the name ends before 様)
_JA_NAME_KANJI = rf"(?:(?!様|殿|氏|君|先生|宛)[{_JA_KANJI}])"
_JA_NAME_END = "[子美江恵代乃枝世香奈郎夫男雄]"  # the kanji a given name written partly in kana ends with
# a word of a name: kanji (a kana part inside, as ゆき子 or ハナ子), or katakana with a kanji ending
_JA_NAME_TOKEN = (
    rf"(?:{_JA_NAME_KANJI}{{1,4}}(?:[{_JA_HIRA}ァ-ヺー]{{1,3}}{_JA_NAME_END})?"
    rf"|{_JA_KANA_WORD}{_JA_NAME_END}?)"
)
_JA_NAME = rf"{_JA_NAME_TOKEN}(?:(?:{_JS}{{1,2}}|[・･]){_JA_NAME_TOKEN})?"  # 山田 花子, ヤマダ・ハナコ
#: the forms a listed surname is written in with old-form (旧字体) or variant kanji: each character's variants
JA_KANJI_VARIANTS = {
    "高": "髙",
    "崎": "﨑嵜碕",
    "斎": "齋齊斉",
    "斉": "齊齋斎",
    "辺": "邊邉",
    "沢": "澤",
    "島": "嶋嶌",
    "浜": "濱",
    "吉": "𠮷",
    "桜": "櫻",
    "広": "廣",
    "国": "國",
    "竜": "龍",
    "条": "條",
    "徳": "德",
    "恵": "惠",
    "富": "冨",
    "関": "關",
    "瀬": "瀨",
    "真": "眞",
    "黒": "黑",
    "滝": "瀧",
    "藤": "籐",
}


def _folded(names: list[str]) -> str:
    return "|".join(
        "".join(f"[{c}{JA_KANJI_VARIANTS[c]}]" if c in JA_KANJI_VARIANTS else c for c in s)
        for s in sorted(names, key=len, reverse=True)
    )


_JP_FOLDED = _folded(list(JP_SURNAMES))
_JP_FOLDED_2 = _folded([s for s in JP_SURNAMES if len(s) > 1])  # never 林 or 森 alone: Chinese names start so too
#: the listed surnames as katakana (フリガナ) writes them
JP_SURNAMES_KANA = (  # noqa: SIM905  (a list of 57 words reads better as text)
    "サトウ スズキ タカハシ タナカ イトウ ワタナベ ヤマモト ナカムラ コバヤシ カトウ ヨシダ ヤマダ ササキ ヤマグチ "
    "マツモト イノウエ キムラ ハヤシ サイトウ シミズ ヤマザキ モリ イケダ ハシモト アベ イシカワ ヤマシタ ナカジマ "
    "イシイ オガワ マエダ オカダ ハセガワ フジタ ゴトウ コンドウ ムラカミ エンドウ アオキ サカモト フクダ オオタ "
    "ニシムラ フジイ カネコ オカモト フジワラ ナカノ ミウラ ハラダ ナカガワ マツダ タケウチ オノ タムラ ナカヤマ ワダ"
).split()
_JP_KANA_LISTED = "|".join(sorted(JP_SURNAMES_KANA, key=len, reverse=True))
# an honorific, then where it ends: 様 (and 君, 氏) never before a kanji (水様便, 様子, 橋本氏病), さん and 殿 never
# before a hiragana that is not a particle (さんざん), 殿 never in a word of its own (殿下, 殿堂)
_JA_HON = (
    rf"(?:さん{_JA_END}|さま{_JA_END}|くん{_JA_END}|ちゃん{_JA_END}|様(?![々]){_JA_END_HARD}|殿(?![下堂様場方内中]){_JA_END}"
    rf"|君{_JA_END_HARD}|氏{_JA_END_HARD}|先生)"
)
_JA_HON_KANJI = (  # never 先生, 氏, 君 after an unlisted kanji word: Chinese says them too
    rf"(?:さん{_JA_END}|さま{_JA_END}|くん{_JA_END}|ちゃん{_JA_END}|様(?![々]){_JA_END_HARD}|殿(?![下堂様場方内中]){_JA_END})"
)
_JA_BOUNDARY = rf"(?:^|(?<=[\s、。，,：:；;（(「『【\[/・]|[{_JA_HIRA}]))"
# a word before 様 that means "-like" (水様の便, 感冒様、): 様 before a kanji is already no honorific
_JA_LIKE = (
    r"水|膿|泥|粘液|血性|漿液|感冒|喘息|痙攣|湿疹|結節|腫瘤|嚢胞|蜂巣|顆粒|線|網|斑|地図|猩紅熱|麻疹|肺炎|髄膜炎|狭心症"
    r"|インフルエンザ|インスリン|ヘパリン|モルヒネ|リウマチ|タール|ポリープ|パーキンソン|ゼリー|コーヒー残渣|すりガラス"
    r"|ステロイド|アレルギー|アトピー|カタル|クループ|ウイルス"
)
# a word before an honorific that names a role, a relative or a group, never a person: 患者様, お母さん, 看護師さん
_JA_NOT_A_NAME_KANJI = (
    r"(?!(?:患者|ご?家族|ご?本人|利用者|入居者|相談者|皆|奥|客|子|旦那|主人|娘|息子|孫|嫁|婿|母|父|祖父|祖母|兄|姉"
    r"|弟|妹|夫|妻|嬢|両親|親|親族|兄弟|姉妹|家人|身内|看護師|看護婦|医師|先生|薬剤師|技師|職員|院長|部長|課長|医長"
    rf"|教授|担当者?|主治医|担当医|同|異|多|各|王|神|仏|苦労|世話|馳走|相手|先方|近所|隣|大工|業者|皆々|殿|{_JA_LIKE})"
    rf"{_JS}?{_JA_HON_KANJI})"
)
_JA_NOT_A_NAME_KANA = (
    r"(?!(?:ナース|ヘルパー|ケアマネ(?:ジャー|ージャー)?|ドクター|スタッフ|ママ|パパ|ベビー|セラピスト|ドライバー"
    rf"|ボランティア|ワーカー|ソーシャルワーカー|ケースワーカー|リハ|オペ|クライアント|ゲスト|メンバー|チーム|ﾅｰｽ|ﾍﾙﾊﾟｰ|{_JA_LIKE})"
    rf"{_JS}?{_JA_HON})"
)
# one katakana word before 様の, 様な or 様に means "-like" (ゼラチン様の結節, ネフローゼ様の浮腫), unless it is a
# listed surname (ヤマダ様のご家族)
_JA_KANA_LIKE = rf"(?!(?!(?:{_JP_KANA_LISTED})様){_JA_KANA_WORD}様[のなに])"
JA_NAME_KANA_HONORIFIC = re.compile(
    rf"(?<![{_JA_KATA}・･]){_JA_NOT_A_NAME_KANA}{_JA_KANA_LIKE}(?P<v>{_JA_KANA_NAME}){_JS}?{_JA_HON}"
)
JA_NAME_LISTED_HONORIFIC = re.compile(
    rf"(?P<v>(?:{_JP_FOLDED})"
    rf"(?:{_JS}?(?:(?!さん|さま|様|くん|ちゃん|殿|先生)[{_JA_KANJI}{_JA_HIRA}ァ-ヺー]){{1,4}})?){_JS}?{_JA_HON}"
)
# a name of four kanji before 先生, a space between them or not (吉川花子先生, 架空一郎 先生): the Chinese rule
# (NAME_HONORIFIC) reads one to three
JA_NAME_KANJI4_SENSEI = re.compile(rf"{_BOUNDARY}{_NOT_A_NAME}(?P<v>{_JA_NAME_KANJI}{{4}}){_JS}?先生")
JA_NAME_KANJI_HONORIFIC = re.compile(
    rf"(?m:{_JA_BOUNDARY}){_JA_NOT_A_NAME_KANJI}"
    rf"(?P<v>{_JA_NAME_KANJI}{{1,4}}(?:{_JS}{_JA_NAME_KANJI}{{1,4}}|{_JA_NAME_KANJI}{{0,3}}))(?<![病症])"
    rf"{_JS}?{_JA_HON_KANJI}"
)
# a kanji of a given name after a listed surname: never the start of a word of a place, a firm, a department or a
# crop variety (松本市, 小林製薬, 松本 歯科, 中野 区役所, 佐藤錦, 山田錦)
_JA_GIVEN_KANJI = (
    rf"(?:(?!医師|看護師|薬剤師|技師|先生|[病症市県区町村郡製薬科医院出在住勤大学会社店屋乳業錦])[{_JA_KANJI}])"
)
# a listed surname with a space and a given name (髙橋 一郎, 佐藤 花子), a two-character surname or longer; and the
# katakana form of one (サトウ ミホコ)
JA_NAME_LISTED_SPACED = re.compile(
    rf"(?P<v>(?:{_JP_FOLDED_2}){_JS}(?:(?:(?!様|殿|氏|君|宛){_JA_GIVEN_KANJI}){{1,3}}|{_JA_KANA_WORD}))"
    rf"(?![{_JA_HIRA}{_JA_KATA}]|{_JA_NAME_KANJI})"
)
JA_NAME_KANA_LISTED = re.compile(
    rf"(?<![{_JA_KATA}])(?P<v>(?:{_JP_KANA_LISTED}){_JS}{{1,2}}{_JA_KANA_WORD})(?![{_JA_KATA}])"
)
# a name of two words and its reading in brackets (山田 太郎（ヤマダ タロウ）): both are masked
JA_NAME_READING = re.compile(
    rf"(?m:{_JA_BOUNDARY})(?P<v>[{_JA_KANJI}]{{1,4}}{_JS}[{_JA_KANJI}]{{1,4}}{_JS}?[（(]"
    rf"(?:{_JA_KANA_WORD}{_JS}{{1,2}}{_JA_KANA_WORD}|[{_JA_HIRA}]{{1,8}}{_JS}{{1,2}}[{_JA_HIRA}]{{1,8}})[)）])"
)
# a name after its label. A label that names nothing else (氏名, フリガナ, 代諾者) takes a separator (a colon, a
# space, a tab, a line break: 氏名確認 is no label) and then a name; a role word (患者, 主治医, 担当者) takes its colon
# and then only a listed surname or a name of two words (患者：意識清明 is no name). A relative's word between them
# (キーパーソン：長男 見本 次郎) stays; a relative's word alone, or a word that describes the patient or the entry
# (患者名：未登録, 記載者：研修医), is no name; nor is a word followed by more of its sentence (なし, を訴える)
_JA_RELATIVES = r"(?:[長次三][男女]|妻|夫|母|父|息子|娘|兄|姉|弟|妹|孫|嫁|本人|家族)"
_JA_RELATIVE = rf"(?:{_JA_RELATIVES}{_JS}{{0,2}})?"
_JA_NOT_A_NAME_VALUE = (
    rf"(?!{_JA_RELATIVES}(?![{_JA_KANJI}{_JA_KATA}])"
    r"|(?:高齢|男性|女性|男児|女児|小児|成人|新生児|乳児|幼児|妊婦|不明|不詳|記載|同上|入院|外来|在宅|未記入|未登録"
    r"|未定|未確認|確認|変更|不在|空欄|研修医|当直医|担当医|主治医|医師|看護師|同意|独歩|意識|発熱|疼痛|方針))"
)
_JA_SEP = r"(?:[ \t　]{0,3}[:：\n][ \t　]{0,3}|[ \t　]{1,3})"  # a table's tab and a line break too
_JA_NAME_LABEL = (
    r"(?:(?:患者氏名|患者名|カナ氏名|氏名カナ|氏名|フリガナ|ふりがな|ﾌﾘｶﾞﾅ|名前|被保険者氏名|記載者|記載医|代諾者"
    rf"|キーパーソン|ｷｰﾊﾟｰｿﾝ|説明者|同席者|立会人|署名者){_JA_SEP}|【(?:患者|患者氏名|患者名|氏名)】{_JS}{{0,3}})"
)
JA_NAME_LABELLED = re.compile(rf"{_JA_NAME_LABEL}{_JA_RELATIVE}{_JA_NOT_A_NAME_VALUE}(?P<v>{_JA_NAME}){_JA_END}")
JA_NAME_READING_LABELLED = re.compile(rf"(?:ふりがな|フリガナ|ﾌﾘｶﾞﾅ){_JA_SEP}(?P<v>{_JA_HIRA_NAME})")
# after a label that names the person: a name in hiragana (two words) or in Latin letters (IMAI Taro, Yoko Yamada)
JA_NAME_LABELLED_OTHER_SCRIPT = re.compile(
    rf"(?:患者氏名|患者名|被保険者氏名|氏名|名前){_JA_SEP}(?!なし|ふめい)"
    rf"(?P<v>[{_JA_HIRA}]{{1,8}}{_JS}{{1,2}}[{_JA_HIRA}]{{1,8}}"
    rf"|[A-Z][A-Za-z'\-]{{1,20}}(?:{_JS}{{1,2}}[A-Z][A-Za-z'\-]{{1,20}}){{1,2}})"
)
# Also one word of three or four kanji, when an age or a sex follows it (患者：見本太郎 68歳 男性) or, after a staff
# word, the line ends with it (主治医：架空次郎); never a word that ends as a disease or a state does (患者：認知症)
_JA_AGE_OR_SEX = (
    rf"{_JS}{{0,3}}[、,，]?{_JS}{{0,3}}(?:[0-9０-９]{{1,3}}{_JS}?(?:歳|才)|男性|女性|[男女](?![{_JA_KANJI}]))"
)
JA_NAME_ROLE_COLON = re.compile(
    rf"(?:(?P<staff>主治医|担当医|担当看護師|担当者)|患者|カナ|ｶﾅ){_JS}{{0,3}}[:：]{_JS}{{0,3}}{_JA_RELATIVE}"
    rf"{_JA_NOT_A_NAME_VALUE}"
    rf"(?P<v>(?:{_JP_FOLDED})(?:{_JS}?{_JA_NAME_TOKEN})?|{_JA_NAME_TOKEN}{_JS}{{1,2}}{_JA_NAME_TOKEN}"
    rf"|{_JA_NAME_KANJI}{{3,4}}(?<![症病炎癌痛熱感中後前済])(?=(?![{_JA_KANJI}])(?:{_JA_AGE_OR_SEX}"
    rf"|(?(staff){_JS}{{0,3}}(?:\n|\Z)|(?!)))))"
    rf"{_JA_END}"
)
# a Japanese name after an English title (Mr. 見本, Ms. 架空 花子); never Dr., which nurses write before an order
# (Dr. 指示, Dr. コール)
JA_NAME_EN_TITLE = re.compile(rf"\b(?:Mr|Mrs|Ms|Miss)\.?{_JS}{{1,2}}{_JA_NOT_A_NAME_VALUE}(?P<v>{_JA_NAME}){_JA_END}")
# a listed surname after a staff or relative word (主治医の佐藤が実施, 長女 田中美咲) or before a staff word
# (佐藤医師より). The name ends there: a given name never starts with a word of a place, a firm or a department
# (長女 松本市在住, 看護師 小林製薬), and a surname alone is followed by a particle or punctuation (母 福田 心療内科)
_JA_STAFF = r"(?:主治医|担当医|執刀医|担当看護師|看護師|医師|薬剤師|技師|担当)"
_JA_SURNAME_THEN = rf"(?:{_JP_FOLDED_2})(?![病症])(?:{_JS}?{_JA_GIVEN_KANJI}{{1,3}}(?![{_JA_KANJI}])"
JA_NAME_LISTED_AFTER_ROLE = re.compile(
    rf"(?:{_JA_RELATIVES}|{_JA_STAFF}){_JS}?の?{_JS}?"
    rf"(?P<v>{_JA_SURNAME_THEN}|(?=[{_JA_PARTICLE}、。，,（()）]|$)))"
)
JA_NAME_LISTED_BEFORE_STAFF = re.compile(
    rf"(?P<v>(?:{_JP_FOLDED_2})(?![病症])(?:{_JS}?{_JA_GIVEN_KANJI}{{1,3}})?){_JS}?(?:医師|看護師|薬剤師|技師)"
)
# the health-insurance card: 記号 and 番号 (a kanji or two before the figures: 東１２), 枝番 (two figures), 公費 and
# 受給者 numbers. A value has three characters or more and a figure (記号１は対照, 記号 A1 of a figure are no card)
_JA_ALNUM = "A-Za-z0-9０-９Ａ-Ｚａ-ｚ"
_JA_INS_VALUE = (
    rf"(?=[^\s、,，。（(]{{0,6}}?[0-9０-９])(?=[{_JA_ALNUM}{_JA_KANJI}\-－‐・･.．/／]{{3}})"
    rf"(?:[{_JA_KANJI}]{{1,3}}{_JS}?)?[{_JA_ALNUM}]{{1,12}}"
    rf"(?:[\-－‐・･.．/／][{_JA_ALNUM}]{{1,12}}){{0,3}}"
)
_JA_IS = rf"{_JS}{{0,3}}(?:は|[:：])?{_JS}{{0,3}}"
_JA_KIGO = r"(?<!図の)(?<!表の)(?<![図表])記号"
JA_INSURANCE_SYMBOL = re.compile(rf"{_JA_KIGO}(?:[・･/／]?番号)?{_JA_IS}(?P<v>{_JA_INS_VALUE})")
JA_INSURANCE_NUMBER = re.compile(
    rf"{_JA_KIGO}{_JA_IS}{_JA_INS_VALUE}[ 　、,，]{{0,3}}番号{_JA_IS}(?P<v>{_JA_INS_VALUE})"
)
JA_INSURANCE_BRANCH = re.compile(rf"枝番(?:号)?{_JS}{{0,3}}[（(]?{_JA_IS}(?P<v>[0-9０-９]{{2}})(?![0-9０-９])")
JA_PUBLIC_NUMBER = re.compile(
    r"(?:公費負担者番号|公費受給者番号|公費番号|負担者番号|受給者証番号|受給者番号|保険証番号|被保険者証番号"
    rf"|資格確認書番号|医療証番号){_JA_IS}(?P<v>{_JA_INS_VALUE})"
)
# a chart or patient number after a label written in full-width letters (患者ＩＤ, カルテＮｏ．), and the other numbers
# of a stay that charts label (入院番号, 検体番号): four characters or more, a figure among them
_JA_NUMBER_VALUE = rf"(?=[^\s、,，。]{{0,4}}[0-9０-９])[{_JA_ALNUM}][{_JA_ALNUM}\-－]{{3,15}}"
JA_MRN_FULLWIDTH = re.compile(
    rf"(?:患者|カルテ|診察券|病歴)(?:ＩＤ|Ｉｄ|ＮＯ|Ｎｏ)[．.]?{_JS}{{0,3}}[:：#＃]?{_JS}{{0,3}}(?P<v>{_JA_NUMBER_VALUE})"
)
JA_NUMBER_LABELLED = re.compile(
    r"(?:入院番号|外来番号|検体番号|受付番号|登録番号|ID番号|ＩＤ番号|予約番号|紹介番号)"
    rf"{_JS}{{0,3}}[:：#＃]?{_JS}{{0,3}}(?P<v>{_JA_NUMBER_VALUE})"
)
# a Japanese telephone number as charts write it: full-width figures, the dashes of Japanese text (－ ‐ ー), the area
# code in brackets, after it or before it, a mobile number without separators, the country code +81. A landline has
# ten figures (the area code and the exchange six together), a mobile eleven: a ratio or a date in brackets has fewer
_JA_Z = "[0０]"
_JA_DASH = "[-－‐‑–—ー―−･・]"  # the dashes of Japanese text, and a middle dot (03･1234･5678)
_JA_AREA_EXCHANGE = ((1, 4), (2, 3), (3, 2), (4, 1))
JA_PHONE = re.compile(
    rf"(?<![\d+＋])(?:{_JA_Z}[5-9５-９]{_JA_Z}{_JA_DASH}?\d{{4}}{_JA_DASH}?\d{{4}}"
    + "".join(
        rf"|{_JA_Z}\d{{{a}}}{_JA_DASH}\d{{{b}}}{_JA_DASH}\d{{4}}"
        rf"|{_JA_Z}\d{{{a}}}[(（]\d{{{b}}}[)）]\d{{4}}"
        rf"|[(（]{_JA_Z}\d{{{a}}}[)）]{_JS}?\d{{{b}}}{_JA_DASH}?\d{{4}}"
        rf"|[+＋][8８][1１]{_JS}?{_JA_DASH}?[(（]?\d{{{a}}}[)）]?{_JS}?{_JA_DASH}?\d{{{b}}}{_JS}?{_JA_DASH}?\d{{4}}"
        for a, b in _JA_AREA_EXCHANGE
    )
    + rf"|[+＋][8８][1１]{_JS}?{_JA_DASH}?[5-9５-９]{_JA_Z}{_JS}?{_JA_DASH}?\d{{4}}{_JS}?{_JA_DASH}?\d{{4}})"
    r"(?!\d)"
)
# a postal code after 〒 or its word, a space or a dash between its parts
JA_POSTAL = re.compile(
    rf"(?:〒|郵便番号|郵便){_JS}{{0,3}}[:：]?{_JS}{{0,3}}"
    rf"(?P<v>\d{{3}}{_JS}{{0,2}}(?:{_JA_DASH}{_JS}{{0,2}})?\d{{4}})(?!\d)"
)
# an e-mail address written with a full-width ＠ (or full-width letters), looked for around each ＠ only
JA_EMAIL_FULLWIDTH = re.compile(
    r"[A-Za-z0-9._%+\-Ａ-Ｚａ-ｚ０-９．＿]{1,64}＠[A-Za-z0-9.\-Ａ-Ｚａ-ｚ０-９．－]{1,255}[.．][A-Za-zＡ-Ｚａ-ｚ]{2,24}"
)
# a date of birth in a Japanese era: the era's letter full-width too (Ｓ３１．３．１４), its first kanji (昭31.3.14),
# the year, month and day in kanji numerals (昭和三十一年三月十四日), spaces between the parts (昭和 31 年 3 月 14 日),
# dashes (S31-03-14), the western year in brackets after the era's (昭和31年（1956年）3月14日)
_JA_ERA = "(?:明治|大正|昭和|平成|令和|[明大昭平令](?=[0-9０-９元])|[MTSHRＭＴＳＨＲ])"
_JA_NUM = "(?:[0-9０-９]{1,2}|元|[一二三四五六七八九十]{1,3})"
_JA_DS = rf"{_JS}{{0,2}}"
_JA_DOB_VALUE = (
    rf"{_JA_ERA}{_JA_DS}{_JA_NUM}{_JA_DS}[年./．／\-－]{_JA_DS}(?:[（(][0-9０-９]{{4}}年?[)）]{_JA_DS})?"
    rf"{_JA_NUM}{_JA_DS}[月./．／\-－]{_JA_DS}{_JA_NUM}(?:{_JA_DS}日)?"
)
JA_DOB_LABELLED = re.compile(rf"{_DOB_LABEL}(?P<v>{_JA_DOB_VALUE})")
JA_DOB_BORN = re.compile(rf"(?P<v>{_JA_DOB_VALUE}){_JS}?(?=生まれ|生(?:$|[\s，,。、;；)）\]】]))")
# an address that starts at its city: with its prefecture, or a city with a ward (横浜市架空区見本町3-12-8); never a
# count after the figures (見本市民病院に2-3回); the building and room after the number (グリーンハイツ203号室)
_JA_ADDR_NO = (
    r"[0-9０-９一二三四五六七八九十]{1,4}(?:(?:丁目|番地?|号|[-－ー‐]|の)[0-9０-９]{0,4}){1,4}"
    r"(?![回次日週錠時年歳ヶか個名人件枚本mｍ])"
)
_JA_PREFECTURE = rf"(?:東京都|北海道|大阪府|京都府|[{_JA_KANJI}]{{2,3}}県)"
JA_ADDRESS_CITY = re.compile(
    rf"(?m:{_JA_BOUNDARY})(?:{_JA_PREFECTURE}[{_JA_KANJI}]{{1,4}}市(?:[{_JA_KANJI}]{{1,4}}区)?"
    rf"|[{_JA_KANJI}]{{1,4}}市[{_JA_KANJI}]{{1,4}}区)[{_JA_KANJI}{_JA_HIRA}ァ-ヺー]{{0,8}}?{_JA_ADDR_NO}"
    rf"(?:{_JS}?[{_JA_KANJI}ァ-ヺーA-Za-zＡ-Ｚａ-ｚ]{{1,15}}{_JS}?[0-9０-９]{{1,4}}号室?)?"
)
JA_ADDRESS_ROOM = re.compile(
    rf"(?<=[0-9０-９])(?P<v>{_JS}?[{_JA_KANJI}ァ-ヺーA-Za-zＡ-Ｚａ-ｚ]{{1,15}}{_JS}?[0-9０-９]{{1,4}}号室)"
)
_JA_HONORIFIC_ANCHOR = re.compile(r"さん|さま|様|くん|君|ちゃん|殿|氏|先生")
_JA_KATA_RX = re.compile(f"[{_JA_KATA}]")
_JA_NAME_LABEL_WORDS = (
    *("氏名", "患者名", "カナ氏名", "フリガナ", "ふりがな", "ﾌﾘｶﾞﾅ", "名前", "記載者", "記載医", "代諾者"),
    *("キーパーソン", "ｷｰﾊﾟｰｿﾝ", "説明者", "同席者", "立会人", "署名者", "【患者", "【氏名"),
)
_JA_RELATIVE_WORDS = (
    *("男", "女", "妻", "夫", "母", "父", "息子", "娘"),
    *("兄", "姉", "弟", "妹", "孫", "嫁", "本人", "家族"),
)
_JA_ROLE_LABELS = ("患者", "主治医", "担当医", "担当看護師", "担当者", "カナ", "ｶﾅ")
_JA_NUMBER_LABELS = (
    "入院番号",
    "外来番号",
    "検体番号",
    "受付番号",
    "登録番号",
    "ID番号",
    "ＩＤ番号",
    "予約番号",
    "紹介番号",
)


def _kata(f: Any) -> bool:
    return _JA_KATA_RX.search(f.text) is not None


def _honorific(f: Any) -> bool:
    return _JA_HONORIFIC_ANCHOR.search(f.text) is not None


#: the 10C-1 rules: (kind, pattern, gate). A gate is a necessary condition of its pattern (D-756), read on the note's
#: :class:`_Facts`; the pattern runs in the window of its anchor where it has one
_JA_RULES: tuple[tuple[str, re.Pattern[str], Callable[[Any], bool]], ...] = (
    ("name", _windowed(JA_NAME_KANA_HONORIFIC, _JA_HONORIFIC_ANCHOR, 40, 3), lambda f: _kata(f) and _honorific(f)),
    ("name", _windowed(JA_NAME_LISTED_HONORIFIC, _JA_HONORIFIC_ANCHOR, 20, 3), _honorific),
    (
        "name",
        _windowed(JA_NAME_KANJI_HONORIFIC, _JA_HONORIFIC_ANCHOR, 12, 3),
        lambda f: f.has("さ", "様", "くん", "ちゃん", "殿"),
    ),
    ("name", _windowed(JA_NAME_KANJI4_SENSEI, re.compile("先生"), 9, 2), lambda f: f.has("先生")),
    ("name", JA_NAME_LISTED_SPACED, lambda f: f.has(" ", "　")),
    ("name", JA_NAME_KANA_LISTED, lambda f: f.has(" ", "　") and _kata(f)),
    ("name", JA_NAME_READING, lambda f: f.has("（", "(") and f.has(" ", "　")),
    ("name", JA_NAME_LABELLED, lambda f: f.has(*_JA_NAME_LABEL_WORDS)),
    ("name", JA_NAME_READING_LABELLED, lambda f: f.has("ふりがな", "フリガナ", "ﾌﾘｶﾞﾅ")),
    ("name", JA_NAME_LABELLED_OTHER_SCRIPT, lambda f: f.has("氏名", "患者名", "名前")),
    ("name", JA_NAME_ROLE_COLON, lambda f: f.has(":", "：") and f.has(*_JA_ROLE_LABELS)),
    ("name", JA_NAME_EN_TITLE, lambda f: f.says("mr", "ms", "miss")),
    ("name", JA_NAME_LISTED_AFTER_ROLE, lambda f: f.has(*_JA_RELATIVE_WORDS, "医", "看護師", "薬剤師", "技師", "担当")),
    ("name", JA_NAME_LISTED_BEFORE_STAFF, lambda f: f.has("医師", "看護師", "薬剤師", "技師")),
    ("id", JA_INSURANCE_SYMBOL, lambda f: f.digit and f.has("記号")),
    ("id", JA_INSURANCE_NUMBER, lambda f: f.digit and f.has("記号")),
    ("id", JA_INSURANCE_BRANCH, lambda f: f.digit and f.has("枝番")),
    ("id", JA_PUBLIC_NUMBER, lambda f: f.digit and f.has("番号")),
    ("mrn", JA_MRN_FULLWIDTH, lambda f: f.digit and f.has("ＩＤ", "Ｉｄ", "ＮＯ", "Ｎｏ")),
    ("mrn", JA_NUMBER_LABELLED, lambda f: f.digit and f.has(*_JA_NUMBER_LABELS)),
    ("phone", JA_PHONE, lambda f: f.digit),
    ("address", JA_POSTAL, lambda f: f.digit and f.has("〒", "郵便")),
    ("email", _windowed(JA_EMAIL_FULLWIDTH, re.compile("＠"), 64, 290, to_line_end=False), lambda f: f.has("＠")),
    (
        "dob",
        JA_DOB_LABELLED,
        lambda f: f.has("出生", "生日", "生年月日", "誕生日") or f.says("dob", "d.o.b", "birth", "born"),
    ),
    ("dob", JA_DOB_BORN, lambda f: _BORN_WORD.search(f.text) is not None),
    ("address", JA_ADDRESS_CITY, lambda f: f.has("市")),
    ("address", JA_ADDRESS_ROOM, lambda f: f.digit and f.has("号室")),
)
#: the 10C-1 rules as (kind, pattern)
JA_NOTE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple((k, rx) for k, rx, _g in _JA_RULES)
#: a finding's kind as the guard names it (``guard.recognisers.NOTE_KINDS``, lower case: the tripwire upper-cases them)
_SCAN_KIND = {"id": "id_number"}

_NOTE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # chart numbers after their label (the site pattern, unlabelled, is added per call)
    (
        "mrn",
        _windowed(
            MRN_LABELLED,
            re.compile(
                r"病歷|病历|病例|病歴|住院號|門診號|病人|病患|歸檔號|カルテ|患者|診察券"
                r"|(?i:mrn|chart|medical record|hospital|admission|visit|patient|insurance|id)"
            ),
            2,
            30,
        ),
    ),
    # dates of birth after their label or before the word for born, and postal addresses (D-745)
    ("dob", DOB_LABELLED),
    ("dob", _windowed(DOB_BORN, re.compile(r"生まれ|出生|生(?:$|[\s，,。、;；)）\]】])|(?i:born)"), 40, 6)),
    ("address", ADDRESS_LABELLED),
    ("address", _windowed(ADDRESS_ZH, re.compile("號"), 90, 40)),
    ("address", ADDRESS_JA),
    ("address", ADDRESS_EN),
    # NEW-B-51 (D-759): around each "@" only, the longest local part (64) before it and the longest domain (255)
    # after: from every position of a long run of digits the shape took 0.65 s
    ("email", _windowed(EMAIL, re.compile("@"), 64, 255, to_line_end=False)),
    # insurance and ID numbers after their label
    ("id", ID_LABELLED),
    ("id", TW_ID),
    # NEW-B-50 (D-756): the shapes the deep review found in notes, one definition each with the guard
    ("id", TW_ARC),
    ("id", TWELVE_DIGITS),
    ("bed", BED_LABELLED),
    ("bed", _windowed(BED_NUMBER, re.compile("床"), 16, 1)),
    ("room", ROOM),
    ("room", ROOM_NUMBER),
    ("phone", PHONE_LABELLED),
    ("name", STAFF_NAME_AFTER),
    ("name", _windowed(STAFF_NAME_BEFORE, _ROLE_ANCHOR, 6, 4)),
    ("name", _windowed(NAME_HONORIFIC, _HONORIFIC_ANCHOR, 6, 3)),
    ("phone", PHONE),
    ("phone", EN_PHONE),
    (
        "phone",
        re.compile(
            r"(?<![\d+])(?:\+81[-\s]?\(?\d{1,4}\)?[-\s]?\d{1,4}[-\s]?\d{4}"
            r"|0[5-9]0[-\s]?\d{4}[-\s]?\d{4}|0\d{1,4}-\d{1,4}-\d{4})(?!\d)"
        ),
    ),
    # names after a role or a label (the writer of the note, a relative), with an honorific, or as the v1 rules find
    # them (patient word, sex and age); only the name is masked, never the title, the sex or the age
    (
        "name",
        re.compile(rf"(?:記載医|記載者|担当医|主治医|家族の|氏名)[\s:：]*(?P<v>(?:{_JP})[\s　]?{_GIVEN_JP}{{1,3}})"),
    ),
    ("name", re.compile(rf"(?:記錄者|紀錄者|家屬|家属|姓名)[\s:：]*(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})")),
    ("name", _windowed(re.compile(rf"(?P<v>(?:{_ROC})(?:(?!科)[{_CJK_N}]){{0,2}}){_ROLE_ZH}"), _ROLE_ANCHOR, 6, 4)),
    ("name", _windowed(re.compile(rf"(?P<v>(?:{_ROC})[{_CJK_N}]{{0,2}}?)\s?{HONORIFIC}"), _HONORIFIC_ANCHOR, 6, 3)),
    ("name", re.compile(rf"{PATIENT_WORD}[：:\s]?(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})(?=[，,、\s(（]|$)")),
    (
        "name",
        re.compile(rf"(?P<v>(?:{_ROC})[{_CJK_N}]{{1,2}})[，,、\s]*[（(]?(?:男|女)[)）]?[，,、\s]*\d{{1,3}}\s?歲"),
    ),
    ("name", re.compile(rf"(?P<v>(?:{_JP})[\s　]?[{_CJK_N}{_KANA_N}]{{1,3}}?)\s?{HONORIFIC}")),
    (
        "name",
        re.compile(
            r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ \t]{1,3}|\b(?:Patient|PATIENT)(?: [Nn]ame)?:[ \t]{0,3}"
            r"|\b(?:Name|NAME)[ \t]{0,3}:[ \t]{0,3})"
            rf"(?P<v>{_SURNAMES}(?:,[ \t]?|[ \t]{{1,2}}){_GIVEN_ANY}(?![A-Za-z])|{_EN_NAME_CAPS}|{_EN_NAME})"
        ),
    ),
    (
        "name",
        re.compile(
            r"\b(?:[Dd]aughter|[Ss]on|[Ww]ife|[Hh]usband|[Mm]other|[Ff]ather|[Ss]ister|[Bb]rother|[Ss]pouse"
            r"|[Pp]artner|[Rr]elative|[Cc]aregiver|[Gg]uardian|[Ss]een by|[Rr]eviewed by|[Dd]ictated by"
            r"|[Bb]rought by|[Aa]ccompanied by)"
            r",?[ \t]{1,3}(?:Dr\.?[ \t]{1,3})?(?!(?:Mr|Mrs|Ms|Miss|Dr)\b)"
            r"(?!(?:Ambulance|EMS|Police|Family|Staff|Self|Taxi|Car|Wheelchair|Stretcher|Friends?|Neighbou?rs?)\b)"
            rf"(?P<v>{_SURNAMES}(?:,[ \t]?|[ \t]{{1,2}}){_GIVEN_ANY}(?![A-Za-z])|{_EN_NAME})"
        ),
    ),
    # NEW-B-55 (D-923): English Taiwan charts; a surname in capitals after a title (Mr. CHEN, Dr. CHEN)
    ("name", re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr)\.?[ \t]{1,3}(?P<v>[A-Z]{2,20}(?:-[A-Z]{2,20})?)\b(?![a-z])")),
    ("name", ROMANISED_TW_NAME),
    ("name", NAME_HAN_AFTER_EN),
    (
        "address",
        _windowed(
            ADDRESS_TW_EN, re.compile(r"\bNo\.?[ \t]?\d"), ADDRESS_TW_EN_BEFORE, ADDRESS_TW_EN_MAX, to_line_end=True
        ),
    ),
    (
        "address",
        _windowed(ADDRESS_TW_EN_CN_ORDER, re.compile(r"\bNo\.?[ \t]?\d"), ADDRESS_TW_EN_MAX, 60, True),
    ),
    *JA_NOTE_PATTERNS,  # 10C-1
)


class _Facts:
    """What a note holds that a pattern needs, found once per note (D-756): a pattern whose words or characters are
    not in the note cannot match it and is not run. Each gate below is a necessary condition of its pattern, never
    a guess (``tests/unit/test_phi_note_cgrd_shapes.py`` checks the spans are the same with and without them)."""

    text: str
    digit: bool
    alpha: bool
    upper: bool
    low: str

    def __init__(self, text: str) -> None:
        self.text = text
        self.digit = _DIGIT.search(text) is not None
        self.alpha = _ALPHA.search(text) is not None
        self.upper = _UPPER.search(text) is not None
        self.low = text.lower() if self.alpha else ""

    def has(self, *words: str) -> bool:
        return any(w in self.text for w in words)

    def says(self, *words: str) -> bool:
        """An English word (lower case) in the note."""
        return self.alpha and any(w in self.low for w in words)


_DIGIT = re.compile(r"\d")  # what the patterns' \\d matches: every Unicode digit
_ALPHA = re.compile(r"[A-Za-z]")
_UPPER = re.compile(r"[A-Z]")
_HAN = re.compile(f"[{_CJK_N}]")
_EN_FULL_ONLY = re.compile(_EN_PHONE_FULL)
# the word each costly pattern cannot match without (a literal first, so the look is fast)
_BORN_WORD: re.Pattern[str] = re.compile(r"生まれ|出生|生(?:$|[\s，,。、;；)）\]】])|(?i:born)")
_ROAD_TO_NO = re.compile(r"(?:路|街|大道|鄰)[^\n]{0,40}?號")
_EN_PHONE_WORD = re.compile(
    r"(?i:\b(?:tel|phone|ph|mobile|mob|cell|fax|pager|landline|helpline|contact|call|dial|home|number))|\b[TM](?=\s*:)"
)
_NUMBER_BED = re.compile(r"\d[^\s床]{0,11}\s?號?床")
_ROLE_WORDS = (
    "醫師",
    "醫生",
    "護理",
    "護士",
    "藥師",
    "個管師",
    "社工師",
    "營養師",
    "治療師",
    "心理師",
    "專師",
    "記錄",
    "紀錄",
)
_HONORIFIC_WORDS = (
    *(
        "先生",
        "小姐",
        "女士",
        "太太",
        "阿嬤",
        "阿公",
        "伯伯",
        "伯母",
        "奶奶",
        "爺爺",
        "媽媽",
        "叔叔",
        "阿姨",
        "婆婆",
        "阿伯",
    ),
    *("君", "さん", "様", "氏", "くん", "ちゃん"),
)
# one gate per entry of _NOTE_PATTERNS, in its order
_NOTE_GATES: tuple[Callable[[_Facts], bool], ...] = (
    lambda f: (
        f.digit
        and (
            f.has(
                "病歷", "病历", "病例", "病歴", "住院號", "門診號", "病人", "病患", "歸檔號", "カルテ", "患者", "診察券"
            )
            or f.says("mrn", "chart", "medical record", "hospital", "admission", "visit", "patient", "insurance", "id")
        )
    ),
    lambda f: (
        f.has("出生", "生日", "生年月日", "誕生日") or f.says("dob", "d.o.b", "birth", "born")
    ),  # 民國四十五年: no digit
    lambda f: _BORN_WORD.search(f.text) is not None,
    lambda f: f.has("地址", "住", "戶籍地", "居所") or f.says("addr"),
    lambda f: _ROAD_TO_NO.search(f.text) is not None,
    lambda f: f.digit and f.has("東京都", "北海道", "大阪府", "京都府", "県"),
    lambda f: f.digit and f.alpha,
    lambda f: "@" in f.text,
    lambda f: (
        f.digit
        and (
            f.has("健保", "身分證", "身份證", "居留證", "統一證號", "保険者番号", "個人番号", "マイナンバー")
            or f.says("insurance", "id", "arc")
        )
    ),
    lambda f: f.digit and f.upper,
    lambda f: f.digit and f.upper,
    lambda f: f.digit,
    lambda f: f.digit and (f.has("床") or f.says("bed")),
    lambda f: _NUMBER_BED.search(f.text) is not None,
    lambda f: f.digit and f.has("病房", "房號", "房号", "病室", "室號", "房間"),
    lambda f: f.digit and f.has("房", "室"),
    lambda f: f.digit and (f.has("電話", "手機", "市話", "携帯") or f.says("tel", "phone", "mobile")),
    lambda f: f.has(*_ROLE_WORDS) or f.says("dr", "np", "rn", "md"),
    lambda f: f.has(*_ROLE_WORDS, "大夫", "教授", "主任"),
    lambda f: f.has(*_HONORIFIC_WORDS),
    lambda f: f.digit,
    lambda f: (
        f.digit
        and ((f.alpha and _EN_PHONE_WORD.search(f.text) is not None) or _EN_FULL_ONLY.search(f.text) is not None)
    ),
    lambda f: f.digit,
    lambda f: f.has("記載医", "記載者", "担当医", "主治医", "家族の", "氏名"),
    lambda f: f.has("記錄者", "紀錄者", "家屬", "家属", "姓名"),
    lambda f: f.has("醫師", "醫生", "護理師", "藥師", "個管師"),
    lambda f: f.has(*_HONORIFIC_WORDS, "老先生", "老太太"),
    lambda f: f.has("病人", "患者", "個案", "病患", "案主", "受試者"),
    lambda f: f.digit and f.has("歲"),
    lambda f: f.has(*_HONORIFIC_WORDS),
    lambda f: f.alpha,
    lambda f: f.alpha,
    lambda f: f.upper and f.has("Mr", "Ms", "Miss", "Dr"),  # Mrs holds Mr
    lambda f: f.upper,  # a surname of the list starts with a capital
    lambda f: f.alpha and _HAN.search(f.text) is not None,
    lambda f: f.digit and f.has("No"),
    lambda f: f.digit and f.has("No"),
    *(g for _k, _rx, g in _JA_RULES),  # 10C-1
)


def find_emails(text: str) -> Iterator[re.Match[str]]:
    """Every email address of ``text`` (:data:`EMAIL`), looked for around each "@" only (NEW-B-51, D-759)."""
    return _finditer(EMAIL, text)


def note_spans(text: str, mrn_regex: str | None = None) -> list[tuple[str, int, int]]:
    """``(kind, start, end)`` of every name, phone number, chart number, ID number, date of birth, postal address
    and email address found in note text, overlaps merged (kinds: ``name``, ``phone``, ``mrn``, ``id``, ``dob``,
    ``address``, ``email``, ``bed``, ``room``).
    ``mrn_regex`` is the site's chart number pattern
    (``settings.mrn_regex``); it also masks a chart number written without its label."""
    found: list[tuple[str, int, int]] = []
    facts = _Facts(text)
    for (kind, rx), gate in zip(_NOTE_PATTERNS, _NOTE_GATES, strict=True):
        if not gate(facts):  # D-756: a pattern whose words the note does not hold cannot match it
            continue
        for m in _finditer(rx, text):
            if "v" in rx.groupindex and m.group("v") is not None:
                found.append((kind, m.start("v"), m.end("v")))
            else:
                found.append((kind, m.start(), m.end()))
    if mrn_regex:
        body = mrn_regex.strip("^$")
        for m in re.finditer(rf"(?<![0-9A-Za-z\-/.]){body}(?![0-9A-Za-z\-/.])", text):
            found.append(("mrn", m.start(), m.end()))
    merged: list[tuple[str, int, int]] = []
    for kind, s, e in sorted(found, key=lambda f: (f[1], -f[2])):
        if e <= s:
            continue
        if merged and s < merged[-1][2]:
            k0, s0, e0 = merged[-1]
            merged[-1] = (k0, s0, max(e0, e))
        else:
            merged.append((kind, s, e))
    return merged


def mask_note(text: str, mrn_regex: str | None = None) -> str:
    """Note text with every span of :func:`note_spans` masked, the length and the white space kept."""
    spans = note_spans(text, mrn_regex)
    if not spans:
        return text
    out = list(text)
    for _kind, s, e in spans:
        for i in range(s, e):
            if not out[i].isspace():
                out[i] = MASK_CHAR
    return "".join(out)


def site_mrn_regex() -> str | None:
    """The site's chart number pattern (``settings.mrn_regex``), or ``None`` when no site configuration is readable
    (a test lake, a tool run without a site): then only labelled chart numbers are masked."""
    try:
        from tb_common.config import get_config

        return get_config().settings.mrn_regex
    except Exception:
        return None
