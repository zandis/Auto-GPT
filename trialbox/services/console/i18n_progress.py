"""The words of the progress lines of a job page (D-1245, card 10E-13, review 13 item 13-14 section 7.1): how far the
first load of a study's new patients has come on a finished screening run, from the run's own night-budget event,
and how many answers the language model has given while a protocol is read.
In en, zh-TW and ja. Joined into ``console.i18n`` (merged with plain ``dict.update``)."""

from __future__ import annotations

EN: dict[str, str] = {
    "job.compile.answers": "Reading the protocol: {n} answers from the language model so far.",
    "job.compile.answers.what": "This counts every answer for this protocol (its parts first, then the codes for "
    "its terms), not the parts themselves.",
    "job.firstload.title": "New patients not yet screened",
    "job.firstload.line": "New patients screened on this run: {n}. Still waiting: {waiting}.",
    "job.firstload.nights": "At this run's pace ({n} new patients on one run), about {nights} more nights. This "
    "is an estimate from this run alone: the night's re-checks, a night shared with other studies, or new patients "
    "arriving change it.",
}

JA: dict[str, str] = {
    "job.compile.answers": "プロトコルを読み取り中：これまでに言語モデルから {n} 件の回答。",
    "job.compile.answers.what": "このプロトコルへのすべての回答（まず各部分、次に用語のコード）の数で、"
    "部分の数ではありません。",
    "job.firstload.title": "まだスクリーニングされていない新しい患者",
    "job.firstload.line": "この実行でスクリーニングした新しい患者：{n} 名。待機中：{waiting} 名。",
    "job.firstload.nights": "この実行のペース（1 回の実行で新しい患者 {n} 名）なら、あと約 {nights} 夜です。"
    "これはこの実行だけからの見込みです。その夜の再確認、ほかの研究と分け合う夜、新しい患者の追加で変わります。",
}

ZH: dict[str, str] = {
    "job.compile.answers": "正在讀取計畫書：目前已收到語言模型 {n} 個回答。",
    "job.compile.answers.what": "這是本計畫書所有回答的數目（先是各部分，再是用語的代碼），不是部分的數目。",
    "job.firstload.title": "尚未篩選的新病人",
    "job.firstload.line": "本次執行篩選的新病人：{n} 位。仍在等待：{waiting} 位。",
    "job.firstload.nights": "以本次執行的速度（一次執行 {n} 位新病人）計，約還需 {nights} 個夜晚。"
    "這只是依本次執行所做的估計：當晚的重新檢查、與其他研究共用夜晚，或有新病人加入，都會改變它。",
}
