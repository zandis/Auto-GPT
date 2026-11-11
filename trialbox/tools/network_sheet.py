"""The one-page network, port and secret sheet (TB-PLAN-04 step 8, D-138), generated from the compose files.

    python -m tools.network_sheet --out docs/handover/network-sheet            # the vendor sheet (every profile)
    python -m tools.network_sheet --files deploy/docker-compose.yml:deploy/docker-compose.secrets.yml:... \\
        --env deploy/.env --out deploy/site/network-sheet                       # a site's sheet (install.sh)
    python -m tools.network_sheet --check docs/handover/network-sheet          # exit 1 when the files differ

Writes ``<out>.<lang>.md`` and ``<out>.<lang>.html`` (A4, prints on one page) in en, ja and zh-TW. Every value comes
from the compose files, the egress rules (``deploy/egress.py``) and the token rules
(``tb_common.service_auth.CALLERS``): every service and every port it listens on, who may reach it, what it may reach
outside the box, and the name and location of every secret, never a value (``--env`` reads only host names for the
egress lines). ``tests/unit/test_network_sheet.py`` compares the sheet with the compose files, so a new service or
port cannot be left out.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "libs",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# the compose files a box we sell runs: the base, the per-service secrets, and the three GPU profiles (D-124)
FILES = (
    "deploy/docker-compose.yml",
    "deploy/docker-compose.secrets.yml",
    "deploy/docker-compose.rtx5090.yml",
    "deploy/docker-compose.gb10.yml",
    "deploy/docker-compose.rtxpro6000.yml",
)
LANGS = ("en", "ja", "zh-TW")
# ports of third-party images that do not say them on the command line
IMAGE_PORTS = {"postgres": 5432, "hapiproject/hapi": 8080, "vllm/vllm-openai": 8000}
# one-shot jobs that listen on nothing (the 5090 sleep swap's start order)
NO_LISTEN = frozenset({"judge-sleep-init", "model-swap-init", "judge-wake-init"})
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")

T: dict[str, dict[str, str]] = {
    "title": {
        "en": "TrialBox network, port and secret sheet",
        "ja": "TrialBox ネットワーク・ポート・秘密情報一覧",
        "zh-TW": "TrialBox 網路、連接埠與機密資訊一覽",
    },
    "intro": {
        "en": "Generated from the compose files below by tools/network_sheet.py (D-138). Nothing on the box is "
        "reachable from outside except the console port. No secret value is on this sheet.",
        "ja": "下記の compose ファイルから tools/network_sheet.py で生成（D-138）。"
        "コンソールのポート以外、外部から到達できるものはありません。秘密情報の値はこの一覧に載せていません。",
        "zh-TW": "由下列 compose 檔以 tools/network_sheet.py 產生（D-138）。"
        "除主控台連接埠外，外部無法連到本機任何服務。本表不含任何機密的值。",
    },
    "files": {"en": "Compose files", "ja": "compose ファイル", "zh-TW": "compose 檔"},
    "ports": {"en": "Listening ports", "ja": "待ち受けポート", "zh-TW": "監聽連接埠"},
    "service": {"en": "Service", "ja": "サービス", "zh-TW": "服務"},
    "port": {"en": "Port", "ja": "ポート", "zh-TW": "連接埠"},
    "host": {"en": "On the host", "ja": "ホスト側", "zh-TW": "主機端"},
    "nets": {"en": "Networks", "ja": "ネットワーク", "zh-TW": "網路"},
    "who": {"en": "Who may reach it", "ja": "接続できるもの", "zh-TW": "可連線者"},
    "when": {"en": "Runs", "ja": "起動条件", "zh-TW": "啟動條件"},
    "always": {"en": "always", "ja": "常時", "zh-TW": "常駐"},
    "not_published": {"en": "not published", "ja": "公開なし", "zh-TW": "未對外"},
    "none": {"en": "none (one-shot job)", "ja": "なし（一回限りの処理）", "zh-TW": "無（一次性工作）"},
    "callers": {
        "en": "with its own token, only: ",
        "ja": "自身のトークンを持つ次のみ: ",
        "zh-TW": "僅限持有自身權杖者: ",
    },
    "operator": {
        "en": "; the administrator on the host (operator token)",
        "ja": "; ホスト上の管理者（operator トークン）",
        "zh-TW": "; 主機上的管理者（operator 權杖）",
    },
    "console": {
        "en": "staff browsers: 127.0.0.1 by default; the hospital LAN only through the site's TLS proxy",
        "ja": "職員のブラウザ: 既定は 127.0.0.1 のみ。院内 LAN からは施設の TLS プロキシ経由のみ",
        "zh-TW": "院內人員瀏覽器: 預設僅 127.0.0.1；院內網路僅經由院方 TLS 代理",
    },
    "db": {
        "en": "TrialBox services and fhir-store, with a password",
        "ja": "TrialBox の各サービスと fhir-store（パスワード）",
        "zh-TW": "TrialBox 各服務與 fhir-store（需密碼）",
    },
    "fhir": {
        "en": "adapter, orchestrator, criteria-compiler (network only, no token yet)",
        "ja": "adapter、orchestrator、criteria-compiler（ネットワーク分離のみ、トークンなし）",
        "zh-TW": "adapter、orchestrator、criteria-compiler（僅網路隔離，尚無權杖）",
    },
    "model": {"en": "gateway only (model-net)", "ja": "gateway のみ（model-net）", "zh-TW": "僅 gateway（model-net）"},
    "model_backend": {
        "en": "model-guard only (model-backend-net; the key on every call, D-177)",
        "ja": "model-guard のみ（model-backend-net。すべての呼び出しに鍵、D-177）",
        "zh-TW": "僅 model-guard（model-backend-net；每次呼叫皆需金鑰，D-177）",
    },
    "nets_h": {"en": "Networks", "ja": "ネットワーク", "zh-TW": "網路"},
    "net_internal": {
        "en": "internal: no route out of the box",
        "ja": "内部専用: 外部への経路なし",
        "zh-TW": "內部專用: 無對外路由",
    },
    "net_egress": {
        "en": "out of the box only to the hosts below (nftables, deploy/network.sh)",
        "ja": "外部へは下表の宛先のみ（nftables、deploy/network.sh）",
        "zh-TW": "對外僅限下表目的地（nftables，deploy/network.sh）",
    },
    "net_console": {
        "en": "the console's published port only: no NAT out, no outside names; nftables drop the rest "
        "(deploy/network.sh)",
        "ja": "コンソールの公開ポート専用: 外部への NAT なし、外部の名前解決なし、"
        "それ以外は nftables で遮断（deploy/network.sh）",
        "zh-TW": "僅供主控台的公開埠: 不做對外 NAT、不解析外部名稱，其餘由 nftables 阻擋（deploy/network.sh）",
    },
    "out_h": {"en": "Outbound", "ja": "外部への通信", "zh-TW": "對外連線"},
    "dest": {"en": "Destination", "ja": "宛先", "zh-TW": "目的地"},
    "why": {"en": "Why", "ja": "用途", "zh-TW": "用途"},
    "out_default": {
        "en": "With no site settings the box reaches nothing outside. ClinicalTrials.gov is offline by default: the "
        "trials come from the reference data pack of each signed update (TB_CTGOV_MODE=offline). A hospital that "
        "chose live at install (TB_CTGOV_MODE=live) opens criteria-compiler to clinicaltrials.gov:443 (public "
        "registry, no patient data). Each line below opens only when its setting is filled in.",
        "ja": "施設設定がなければ外部には何も接続しません。ClinicalTrials.gov は既定でオフラインです。"
        "試験情報は署名付き"
        "更新に含まれる参照データから読みます（TB_CTGOV_MODE=offline）。導入時に live を選んだ病院では "
        "criteria-compiler から clinicaltrials.gov:443 に接続します（公開レジストリ、患者データなし。"
        "TB_CTGOV_MODE=live）。下表の各行は、その設定を入れたときだけ開きます。",
        "zh-TW": "未做院方設定時，本機不對外連線。ClinicalTrials.gov 預設為離線：試驗資料來自每次簽章更新附帶的參考資料"
        "（TB_CTGOV_MODE=offline）。安裝時選擇 live 的醫院，criteria-compiler 會連 clinicaltrials.gov:443"
        "（公開登錄，無病人資料；TB_CTGOV_MODE=live）。下表每一列僅在填入該設定後開放。",
    },
    "ctgov_live": {
        "en": "ClinicalTrials.gov: live (chosen at install). criteria-compiler reaches clinicaltrials.gov:443; no "
        "patient data is sent.",
        "ja": "ClinicalTrials.gov：live（導入時に選択）。criteria-compiler が clinicaltrials.gov:443 に接続します。"
        "患者データは送りません。",
        "zh-TW": "ClinicalTrials.gov：live（安裝時選擇）。criteria-compiler 連 clinicaltrials.gov:443；"
        "不傳送病人資料。",
    },
    "ctgov_offline": {
        "en": "ClinicalTrials.gov: offline (chosen at install). No outbound access; the trials come from the "
        "reference data pack of each signed update.",
        "ja": "ClinicalTrials.gov：オフライン（導入時に選択）。外部へは接続しません。試験情報は署名付き更新に含まれる"
        "参照データから読みます。",
        "zh-TW": "ClinicalTrials.gov：離線（安裝時選擇）。不對外連線；試驗資料來自每次簽章更新附帶的參考資料。",
    },
    "ctgov_cassette": {
        "en": "ClinicalTrials.gov: cassette (test and demo box only). No outbound access.",
        "ja": "ClinicalTrials.gov：cassette（試験・デモ機のみ）。外部へは接続しません。",
        "zh-TW": "ClinicalTrials.gov：cassette（僅測試與展示機）。不對外連線。",
    },
    "setting": {"en": "Opened by", "ja": "開く設定", "zh-TW": "開放條件"},
    "secrets_h": {
        "en": "Secrets (names and places only)",
        "ja": "秘密情報（名前と場所のみ）",
        "zh-TW": "機密資訊（僅名稱與位置）",
    },
    "secret": {"en": "Secret", "ja": "秘密情報", "zh-TW": "機密"},
    "where": {"en": "Kept in", "ja": "保管場所", "zh-TW": "存放位置"},
    "given": {"en": "Given to", "ja": "渡す先", "zh-TW": "提供給"},
    "rotate": {
        "en": "Rotate: sudo python3 -m tools.trialbox secrets rotate [--service NAME] (RUNBOOK §5 'Secrets').",
        "ja": "更新: sudo python3 -m tools.trialbox secrets rotate [--service 名前]（RUNBOOK §5「Secrets」）。",
        "zh-TW": "輪替: sudo python3 -m tools.trialbox secrets rotate [--service 名稱]（RUNBOOK §5「Secrets」）。",
    },
    "host_only": {
        "en": "the host only; never in a container",
        "ja": "ホストのみ（コンテナには渡さない）",
        "zh-TW": "僅主機（不進容器）",
    },
    "every": {
        "en": "every TrialBox service (hashes only, not secret)",
        "ja": "全 TrialBox サービス（ハッシュのみ、秘密ではない）",
        "zh-TW": "所有 TrialBox 服務（僅雜湊，非機密）",
    },
    "hospital_it": {
        "en": "hospital IT, sealed envelope; never on the box",
        "ja": "病院情報部門が封筒で保管。本機には置かない",
        "zh-TW": "醫院資訊室密封保管；不放在本機",
    },
}

T["profile_gpu"] = {"en": "GPU profile", "ja": "GPU プロファイル", "zh-TW": "GPU 設定"}
T["profile_stub"] = {"en": "no-GPU profile", "ja": "GPU なしプロファイル", "zh-TW": "無 GPU 設定"}


@dataclass
class Service:
    name: str
    image: str = ""
    ports: list[int] = field(default_factory=list)
    published: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)


def interpolate(s: str, env: dict[str, str] | None = None) -> str:
    """``${VAR:-default}`` with the site's value (``env``) or the default, as compose does."""
    env = env or {}
    return _VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), s)


def _merge(a: Any, b: Any) -> Any:
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(a[k], v) if k in a else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        return a + [x for x in b if x not in a]
    return b


def load(files: list[str], root: Path = ROOT) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    origin: dict[str, list[str]] = {}
    for f in files:
        data = yaml.safe_load((root / f).read_text(encoding="utf-8")) or {}
        for name in data.get("services") or {}:
            origin.setdefault(name, []).append(Path(f).name)
        merged = _merge(merged, data)
    merged["_origin"] = origin
    return merged


def ports_of(svc: dict[str, Any]) -> list[int]:
    cmd = svc.get("command") or []
    cmd = cmd if isinstance(cmd, list) else str(cmd).split()
    out: list[int] = []
    for i, a in enumerate(cmd):
        a = str(a)
        if a == "--port" and i + 1 < len(cmd):
            out.append(int(interpolate(str(cmd[i + 1]))))
        elif a.startswith("--port="):
            out.append(int(interpolate(a.split("=", 1)[1])))
    for e in svc.get("expose") or []:
        out.append(int(str(e).split("/")[0]))
    image = str(svc.get("image") or "")
    if not out:
        for key, port in IMAGE_PORTS.items():
            if key in image:
                out.append(port)
    return sorted(set(out))


def services(files: list[str], env: dict[str, str] | None = None, root: Path = ROOT) -> list[Service]:
    data = load(files, root)
    out = []
    for name, svc in sorted((data.get("services") or {}).items()):
        s = Service(name, interpolate(str(svc.get("image") or ""), env))
        s.ports = [] if name in NO_LISTEN else ports_of(svc)
        s.published = [interpolate(str(p), env) for p in svc.get("ports") or []]
        nets = svc.get("networks") or ["default"]
        s.networks = sorted(nets if isinstance(nets, list) else nets.keys())
        s.profiles = list(svc.get("profiles") or [])
        s.files = data["_origin"].get(name, [])
        s.secrets = [str(x["source"] if isinstance(x, dict) else x) for x in svc.get("secrets") or []]
        envmap = svc.get("environment") or {}
        if isinstance(envmap, dict):
            s.cleared = sorted(
                k for k, v in envmap.items() if v == "" and k not in ("TB_GATEWAY_MODEL", "TB_DATA_CLASS")
            )
        out.append(s)
    return out


def who(s: Service, lang: str) -> str:
    from tb_common.service_auth import CALLERS

    if s.name == "console":
        return T["console"][lang]
    if s.name == "db":
        return T["db"][lang]
    if s.name == "fhir-store":
        return T["fhir"][lang]
    if s.name in ("model-guard", "llm-stub"):
        return T["model"][lang]
    if s.name in ("llm-service", "llm-verifier"):
        return T["model_backend"][lang]
    if s.name in NO_LISTEN:
        return "-"
    if s.name in CALLERS:
        return T["callers"][lang] + ", ".join(sorted(CALLERS[s.name])) + T["operator"][lang]
    raise KeyError(f"no 'who may reach it' rule for service {s.name}: add one to tools/network_sheet.py")


def _egress_module() -> Any:
    spec = importlib.util.spec_from_file_location("tb_egress", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclasses look themselves up there
    spec.loader.exec_module(mod)
    return mod


# every outbound rule of deploy/egress.py, with the setting that opens it (site values come from --env)
OUTBOUND = (
    ("mail-gateway", "SMTP_HOST:SMTP_PORT", "outbound mail (hospital SMTP / Exchange)", "SMTP_HOST"),
    ("mail-gateway", "IMAP_HOST:IMAP_PORT", "intake mailbox", "IMAP_HOST"),
    (
        "gateway",
        "external model endpoints of models/routing.yaml",
        "model endpoint (refused for D3/D4 data)",
        "the endpoint's URL",
    ),
    (
        "criteria-compiler",
        "clinicaltrials.gov:443",
        "ClinicalTrials.gov public registry (COHORT)",
        "TB_CTGOV_MODE=live (chosen at install; the default is offline)",
    ),
    ("orchestrator", "NHI_TWPAS_BASE_URL", "NHI TWPAS (SUBMIT only)", "NHI_TWPAS_BASE_URL"),
    ("any", "EGRESS_EXTRA", "site additions", "EGRESS_EXTRA"),
)


def outbound(env: dict[str, str] | None) -> list[tuple[str, str, str, str]]:
    if env is None:
        return list(OUTBOUND)
    allows = _egress_module().allowlist(env)
    return [(a.service, f"{a.host}:{a.port}", a.why, "") for a in allows]


def ctgov_key(env: dict[str, str]) -> str:
    """The sheet's ClinicalTrials.gov line for the site's mode (D-140: offline unless live was chosen)."""
    mode = (env.get("TB_CTGOV_MODE") or "offline").strip().lower()
    return f"ctgov_{mode}" if mode in ("live", "offline", "cassette") else "ctgov_offline"


def secrets_rows(svcs: list[Service], lang: str) -> list[tuple[str, str, str]]:
    by_secret: dict[str, list[str]] = {}
    for s in svcs:
        for sec in s.secrets:
            by_secret.setdefault(sec, []).append(s.name)
    rows = []
    for sec, names in sorted(by_secret.items()):
        svc = sec.removeprefix("token_")
        rows.append((f"service token: {svc}", f"deploy/secrets/services/{svc}.token (0600)",
                     f"{', '.join(names)} only, at /run/secrets/tb_service_token"))  # fmt: skip
    keys = ("IMAP_PASS", "SMTP_PASS", "CLOUD_LLM_API_KEY", "TB_DB_URL", "POSTGRES_WF_PASSWORD")
    cleared = {k: [s.name for s in svcs if k in s.cleared] for k in keys}
    py = sorted({s.name for s in svcs if s.secrets})

    def keep(key: str) -> str:
        return ", ".join(n for n in py if n not in cleared[key]) or "-"

    rows += [
        ("operator token", "deploy/secrets/services/operator.token (0600)", T["host_only"][lang]),
        ("token registry (sha256 of each token)", "deploy/secrets/services/public/tokens.json", T["every"][lang]),
        ("POSTGRES_PASSWORD (role hapi)", "deploy/.env (0600, root)", "db, fhir-store"),
        ("POSTGRES_WF_PASSWORD, TB_DB_URL (role trialbox)", "deploy/.env (0600, root)", "db; " + keep("TB_DB_URL")),
        ("IMAP_PASS, SMTP_PASS", "deploy/.env (0600, root)", keep("IMAP_PASS")),
        ("CLOUD_LLM_API_KEY (empty by default)", "deploy/.env (0600, root)", keep("CLOUD_LLM_API_KEY")),
        (
            "site_hmac.key, pid_map.key, REDCap API tokens",
            "volume tb-secrets (/run/secrets/trialbox)",
            "adapter, orchestrator",
        ),
        ("backup public key", "deploy/secrets/backup.pub", "the backup (encrypts only)"),
        ("backup private key", "USB stick", T["hospital_it"][lang]),
        ("vendor update key (public)", "deploy/keys/vendor_ed25519.pub", "tools/apply_update.sh"),
    ]
    return rows


def _when(s: Service, lang: str) -> str:
    if not s.profiles:
        return T["always"][lang]
    p = ", ".join(T.get(f"profile_{x}", {}).get(lang, x) for x in s.profiles)
    if "docker-compose.yml" in s.files:  # defined in the base file: its profile says when it runs
        return p
    overlays = [
        f.replace("docker-compose.", "").replace(".yml", "") for f in s.files if f != "docker-compose.secrets.yml"
    ]
    return p + (f" ({', '.join(overlays)})" if overlays else "")


def tables(files: list[str], env: dict[str, str] | None, lang: str, root: Path = ROOT) -> dict[str, Any]:
    svcs = services(files, env, root)
    ports = [
        (s.name, ", ".join(str(p) for p in s.ports) or T["none"][lang],
         ", ".join(s.published) or T["not_published"][lang], ", ".join(s.networks), who(s, lang), _when(s, lang))
        for s in svcs
    ]  # fmt: skip
    data = load(files, root)
    nets = []
    for n, spec in sorted((data.get("networks") or {}).items()):
        name = (spec or {}).get("name", n)
        kind = "net_internal" if (spec or {}).get("internal") else "net_console" if n == "console-net" else "net_egress"
        nets.append((name, T[kind][lang]))
    return {"services": svcs, "ports": ports, "nets": nets, "out": outbound(env), "secrets": secrets_rows(svcs, lang)}


def _md_table(head: list[str], rows: list[tuple[str, ...]]) -> str:
    esc = [[c.replace("|", "\\|") for c in r] for r in rows]
    return "\n".join(["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
                     + ["| " + " | ".join(r) + " |" for r in esc])  # fmt: skip


def render_md(files: list[str], env: dict[str, str] | None, lang: str, root: Path = ROOT) -> str:
    t = tables(files, env, lang, root)

    def L(k: str) -> str:  # noqa: N802
        return T[k][lang]

    parts = [
        f"# {L('title')}",
        L("intro"),
        f"**{L('files')}:** " + ", ".join(f"`{f}`" for f in files),
        f"## {L('ports')}",
        _md_table([L("service"), L("port"), L("host"), L("nets"), L("who"), L("when")], t["ports"]),
        f"## {L('nets_h')}",
        _md_table([L("nets"), ""], t["nets"]),
        f"## {L('out_h')}",
        L("out_default") if env is None else L(ctgov_key(env)),
        _md_table([L("service"), L("dest"), L("why"), L("setting")], t["out"]) if t["out"] else "-",
        f"## {L('secrets_h')}",
        _md_table([L("secret"), L("where"), L("given")], t["secrets"]),
        L("rotate"),
    ]
    return "\n\n".join(p for p in parts if p) + "\n"


CSS = (
    "@page{size:A4 landscape;margin:8mm}body{font-family:'Noto Sans JP','Noto Sans TC',sans-serif;font-size:8.5pt;"
    "margin:0;color:#111;background:#fff}h1{font-size:13pt;margin:0 0 4px}h2{font-size:10pt;margin:8px 0 3px}"
    "p{margin:2px 0}table{border-collapse:collapse;width:100%}td,th{border:1px solid #999;padding:1px 4px;"
    "vertical-align:top;text-align:left}th{background:#eee}code{font-size:8pt}"
)


def render_html(files: list[str], env: dict[str, str] | None, lang: str, root: Path = ROOT) -> str:
    t = tables(files, env, lang, root)

    def L(k: str) -> str:  # noqa: N802
        return html.escape(T[k][lang])

    def table(head: list[str], rows: list[tuple[str, ...]]) -> str:
        th = "".join(f"<th>{h}</th>" for h in head)
        trs = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table><tr>{th}</tr>{trs}</table>"

    body = [
        f"<h1>{L('title')}</h1><p>{L('intro')}</p>",
        f"<p><b>{L('files')}:</b> " + ", ".join(f"<code>{html.escape(f)}</code>" for f in files) + "</p>",
        f"<h2>{L('ports')}</h2>"
        + table([L("service"), L("port"), L("host"), L("nets"), L("who"), L("when")], t["ports"]),
        f"<h2>{L('nets_h')}</h2>" + table([L("nets"), ""], t["nets"]),
        f"<h2>{L('out_h')}</h2>"
        + (f"<p>{L('out_default')}</p>" if env is None else f"<p>{L(ctgov_key(env))}</p>")
        + (table([L("service"), L("dest"), L("why"), L("setting")], t["out"]) if t["out"] else "<p>-</p>"),
        f"<h2>{L('secrets_h')}</h2>"
        + table([L("secret"), L("where"), L("given")], t["secrets"])
        + f"<p>{L('rotate')}</p>",
    ]
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{L("title")}</title>'
            f"<style>{CSS}</style></head><body>{''.join(body)}</body></html>\n")  # fmt: skip


def write(out: Path, files: list[str], env: dict[str, str] | None, root: Path = ROOT) -> list[Path]:
    out.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for lang in LANGS:
        for ext, fn in (("md", render_md), ("html", render_html)):
            p = out.with_name(f"{out.name}.{lang}.{ext}")
            p.write_text(fn(files, env, lang, root), encoding="utf-8")
            written.append(p)
    return written


def read_env(path: Path) -> dict[str, str]:
    """Only what the egress rules read (host names, ports, modes); no password is read."""
    keep = {"SMTP_HOST", "SMTP_PORT", "IMAP_HOST", "IMAP_PORT", "CLOUD_LLM_BASE_URL", "TB_CTGOV_MODE",
            "NHI_TWPAS_BASE_URL", "EGRESS_EXTRA", "TB_CONSOLE_BIND", "TB_HOST_CONSOLE_PORT"}  # fmt: skip
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if k.strip() in keep or (k.strip().endswith("_BASE_URL") and "KEY" not in k):
            out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--files", default=":".join(FILES), help="colon-separated compose files, relative to trialbox/")
    ap.add_argument("--env", type=Path, default=None, help="the site's deploy/.env (host names only are read)")
    ap.add_argument("--out", type=Path, default=Path("docs/handover/network-sheet"))
    ap.add_argument("--check", action="store_true", help="compare with the files at --out instead of writing")
    a = ap.parse_args(argv)
    files = [f for f in a.files.split(":") if f]
    env = read_env(a.env) if a.env else None
    if a.check:
        stale = []
        for lang in LANGS:
            for ext, fn in (("md", render_md), ("html", render_html)):
                p = a.out.with_name(f"{a.out.name}.{lang}.{ext}")
                if not p.is_file() or p.read_text(encoding="utf-8") != fn(files, env, lang, ROOT):
                    stale.append(str(p))
        print("up to date" if not stale else "stale: " + ", ".join(stale) + " (python -m tools.network_sheet)")
        return 1 if stale else 0
    for p in write(a.out, files, env):
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
