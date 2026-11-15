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
# names without a listed surname, wider labelled values, D-756)
NOTE_MASK_VERSION = "4"

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
_NOTE_WINDOWS: dict[int, tuple[re.Pattern[str], int, int]] = {}


def _windowed(rx: re.Pattern[str], anchor: re.Pattern[str], before: int, after: int) -> re.Pattern[str]:
    _NOTE_WINDOWS[id(rx)] = (anchor, before, after)
    return rx


def _finditer(rx: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """``rx.finditer(text)``, or for a windowed pattern its matches in the window around each anchor (overlapping
    windows joined; a window runs on to its line's end, so a look ahead reads what it would in the whole note)."""
    win = _NOTE_WINDOWS.get(id(rx))
    if win is None:
        yield from rx.finditer(text)
        return
    anchor, before, after = win
    spans: list[list[int]] = []
    for a in anchor.finditer(text):
        lo, hi = max(0, a.start() - before), min(len(text), a.end() + after)
        end = text.find("\n", hi)
        hi = len(text) if end < 0 else end
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    for lo, hi in spans:
        yield from rx.finditer(text, lo, hi)


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
    ("email", EMAIL),
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
        re.compile(r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+|\bPatient(?: name)?:\s*)(?P<v>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"),
    ),
    (
        "name",
        re.compile(
            r"\b(?:[Dd]aughter|[Ss]on|[Ww]ife|[Hh]usband|[Mm]other|[Ff]ather|[Ss]ister|[Bb]rother|[Ss]pouse"
            r"|[Pp]artner|[Rr]elative|[Ss]een by|[Rr]eviewed by|[Dd]ictated by|[Nn]ame\s*[:：])"
            r"\s+(?:Dr\.?\s+)?(?!(?:Mr|Mrs|Ms|Miss|Dr)\b)(?P<v>[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)?)"
        ),
    ),
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
_EN_FULL_ONLY = re.compile(_EN_PHONE_FULL)
# the word each costly pattern cannot match without (a literal first, so the look is fast)
_BORN_WORD = re.compile(r"生まれ|出生|生(?:$|[\s，,。、;；)）\]】])|(?i:born)")
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
)


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
