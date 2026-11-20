# ruff: noqa: E501 - one string per line, as in the other catalogues
"""Words of a person's own preferences on the account page (10F-1, D-1387): density, text size, colour mode and
language, and the message of each field when a value outside its set is posted. Joined into ``console.i18n`` by
``console.step4`` (the account page's module) when it is imported."""

from __future__ import annotations

EN: dict[str, str] = {
    "pref.title": "How your pages look",
    "pref.help": "Only for you, on every device you sign in on. It changes how your pages look and their language, never what you can open or who is told what.",
    "pref.save": "Save how my pages look",
    "pref.saved": "Saved. Your pages look like this until you change it, after you sign out too.",
    "pref.density": "Spacing",
    "pref.density.comfortable": "Comfortable",
    "pref.density.compact": "Compact",
    "pref.text_size": "Text size",
    "pref.text_size.100": "100 %",
    "pref.text_size.125": "125 %",
    "pref.text_size.150": "150 %",
    "pref.mode": "Colours",
    "pref.mode.system": "As this device is set",
    "pref.mode.light": "Light",
    "pref.mode.dark": "Dark",
    "pref.mode.contrast": "High contrast",
    "pref.lang.auto": "As chosen when signing in",
    "fe.pref.density": "Choose the spacing from the list: comfortable or compact.",
    "fe.pref.text_size": "Choose the text size from the list: 100 %, 125 % or 150 %.",
    "fe.pref.mode": "Choose the colours from the list: as this device is set, light, dark or high contrast.",
    "fe.pref.lang": "Choose the language from the list.",
}

JA: dict[str, str] = {
    "pref.title": "画面の見え方",
    "pref.help": "あなただけの設定で、ログインするどの端末でも使われます。画面の見え方と言語だけを変え、開ける画面や誰に何が知らされるかは変えません。",
    "pref.save": "画面の見え方を保存",
    "pref.saved": "保存しました。変更するまで、ログアウトした後もこの見え方になります。",
    "pref.density": "間隔",
    "pref.density.comfortable": "ゆったり",
    "pref.density.compact": "コンパクト",
    "pref.text_size": "文字の大きさ",
    "pref.text_size.100": "100 %",
    "pref.text_size.125": "125 %",
    "pref.text_size.150": "150 %",
    "pref.mode": "配色",
    "pref.mode.system": "この端末の設定どおり",
    "pref.mode.light": "ライト",
    "pref.mode.dark": "ダーク",
    "pref.mode.contrast": "ハイコントラスト",
    "pref.lang.auto": "ログイン時の選択どおり",
    "fe.pref.density": "間隔は一覧から選んでください（ゆったり、またはコンパクト）。",
    "fe.pref.text_size": "文字の大きさは一覧から選んでください（100 %、125 %、150 %）。",
    "fe.pref.mode": "配色は一覧から選んでください（この端末の設定どおり、ライト、ダーク、ハイコントラスト）。",
    "fe.pref.lang": "言語は一覧から選んでください。",
}

ZH: dict[str, str] = {
    "pref.title": "頁面的外觀",
    "pref.help": "只屬於您，在您登入的每部裝置上都適用。只改變頁面的外觀與語言，不改變您能開啟的頁面，也不改變誰會收到什麼通知。",
    "pref.save": "儲存頁面的外觀",
    "pref.saved": "已儲存。在您變更之前，登出後頁面也會維持這個外觀。",
    "pref.density": "間距",
    "pref.density.comfortable": "寬鬆",
    "pref.density.compact": "緊湊",
    "pref.text_size": "文字大小",
    "pref.text_size.100": "100 %",
    "pref.text_size.125": "125 %",
    "pref.text_size.150": "150 %",
    "pref.mode": "配色",
    "pref.mode.system": "依此裝置的設定",
    "pref.mode.light": "淺色",
    "pref.mode.dark": "深色",
    "pref.mode.contrast": "高對比",
    "pref.lang.auto": "依登入時的選擇",
    "fe.pref.density": "請從清單選擇間距：寬鬆或緊湊。",
    "fe.pref.text_size": "請從清單選擇文字大小：100 %、125 % 或 150 %。",
    "fe.pref.mode": "請從清單選擇配色：依此裝置的設定、淺色、深色或高對比。",
    "fe.pref.lang": "請從清單選擇語言。",
}
