"""Localized O-6 aggregate report."""

from tools.japanese_context import MIX, PROFILES, Arm, compare

_KEYS = [
    "title",
    "ballast",
    "head-box",
    "context",
    "seed",
    "patients",
    "fixture",
    "rules",
    "judge_calls",
    "truncated_calls",
    "input_tokens",
    "output_tokens",
    "missing_judge_calls",
    "verifier_calls",
    "share",
    "status",
    "complete",
    "incomplete",
    "difference",
    "pass",
    "fail",
    "invalid",
    "usage",
]

TEXT = {
    "en": dict(
        zip(
            _KEYS,
            (
                "O-6 Japanese SCREEN context comparison",
                "8k ballast stand-in",
                "32k unballasted head-box control",
                "Context (tokens)",
                "Synthetic seed",
                "Generated patients",
                "Fixture SHA-256",
                "GZQO rules SHA-256",
                "Judge calls with usage (denominator)",
                "Truncated judge calls",
                "Judge input tokens",
                "Judge output tokens",
                "Judge calls without usable observations",
                "Verifier calls",
                "Truncation share",
                "Status",
                "Complete",
                "Incomplete",
                "Difference (percentage points)",
                "Pass",
                "Fail",
                "Invalid rehearsal input.",
                "Use capture <ballast|head-box> <folder> <seed> or report <folder>.",
            ),
            strict=True,
        )
    ),
    "zh-TW": dict(
        zip(
            _KEYS,
            (
                "O-6 日文 SCREEN 上下文比較",
                "8k 顯示記憶體預留替代測試",
                "32k 未預留顯示記憶體的主工作站對照",
                "上下文（權杖數）",
                "合成資料亂數種子",
                "合成病人數",
                "測試資料 SHA-256",
                "GZQO 規則 SHA-256",
                "具有用量資料的判定呼叫數（分母）",
                "截斷的判定呼叫數",
                "判定模型輸入權杖數",
                "判定模型輸出權杖數",
                "缺少可用觀測資料的判定呼叫數",
                "覆核呼叫數",
                "截斷比例",
                "狀態",
                "完整",
                "未完成",
                "差值（百分點）",
                "通過",
                "未通過",
                "演練輸入無效。",
                "請使用 capture <ballast|head-box> <目錄> <種子> 或 report <目錄>。",
            ),
            strict=True,
        )
    ),
    "ja": dict(
        zip(
            _KEYS,
            (
                "O-6 日本語 SCREEN のコンテキスト比較",
                "8k GPU メモリ予約による代替試験",
                "32k メモリ予約なしの主任端末対照",
                "コンテキスト（トークン数）",
                "合成データのシード",
                "生成患者数",
                "試験データの SHA-256",
                "GZQO ルールの SHA-256",
                "使用量を取得した判定呼び出し数（分母）",
                "切り詰めた判定呼び出し数",
                "判定モデルの入力トークン数",
                "判定モデルの出力トークン数",
                "有効な観測値のない判定呼び出し数",
                "検証呼び出し数",
                "切り詰め率",
                "状態",
                "完了",
                "未完了",
                "差（パーセントポイント）",
                "合格",
                "不合格",
                "試験入力が無効です。",
                "capture <ballast|head-box> <フォルダー> <シード> または report <フォルダー> を使用してください。",
            ),
            strict=True,
        )
    ),
}


def render(ballast: Arm, control: Arm, locale: str) -> str:
    t = TEXT[locale]
    lines = [f"# {t['title']}"]
    for arm in (ballast, control):
        lines.extend(("", f"## {t[arm.profile]}", "", f"- {t['context']} — {PROFILES[arm.profile]:,}"))
        if p := arm.provenance:
            lines.extend(
                (
                    f"- {t['seed']} — {p.seed} ({MIX})",
                    f"- {t['patients']} — {p.patients}",
                    f"- {t['fixture']} — `{p.fixture_sha256}`",
                    f"- {t['rules']} — `{p.rules_sha256}`",
                )
            )
        for key, value in vars(arm.counts).items():
            lines.append(f"- {t[key]} — {value}")
        share = arm.counts.share
        lines.append(f"- {t['share']} — " + ("–" if share is None else f"{float(100 * share):.8g}%"))
        lines.append(f"- {t['status']} — {t['complete' if arm.complete else 'incomplete']}")
    difference, passed = compare(ballast, control)
    lines.extend(("", "## A6", ""))
    if difference is None:
        lines.append(t["incomplete"])
    else:
        lines.extend((f"- {t['difference']} — {float(difference):+.8g}", f"- {t['pass' if passed else 'fail']}"))
    return "\n".join(lines) + "\n"
