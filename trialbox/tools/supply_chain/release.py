"""Release gates (D-186): every shipped image, by digest and platform, scanned and recorded before a bundle is made.

    python -m tools.supply_chain release-gates --cache-dir .cache/trivy --image trialbox-py:1.0.0 \\
        --image registry:vllm/vllm-openai:v0.32.0=linux/amd64 --image registry:REF@sha256:...=linux/arm64

For each image the gate first pins it: a local image by its image id (``docker image inspect``), a registry image
(``registry:`` prefix) by its ``@sha256`` digest (a tag is resolved to its digest first, with ``docker buildx
imagetools inspect``) and a platform. Trivy (offline DB) and Syft then scan it, and the gate checks that both
reports name that same image. The lock's SBOM (``make lock-sbom``) is read too. The licence gate runs over all
SBOMs. The record, ``gates.json``, lists per image: reference, platform, image id, repo digests, the report and SBOM
files with their sha256, and the result. ``dist/sbom/index.json`` lists the SBOMs the same way.

``bundle-check`` reads that record: ``tools/make_bundle.sh --gates`` refuses an image whose local image id (its config
digest, the same for a pulled image and its registry scan) is not in a passing record.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.supply_chain import licences, sbom, vulns
from tools.supply_chain.allowlist import Allowlist

# Report mode is left only for the test-only mail servers of deploy/docker-compose.test.yml (T-110b, ENG-007): no
# bundle carries them (tools/make_bundle.sh leaves the test file out, OPS-017), and bundle_problems refuses any image
# with a report-mode finding anyway. Every image a bundle can carry blocks: ours, and the third-party HAPI FHIR, vLLM
# and identity images, whose open findings are dated per-image entries of deploy/supply-chain-allowlist.yaml
# (deploy/security/known-image-findings.md). D-827: the mail servers are report-only in every mode, block too (their
# newest releases carry the findings, no patched tag exists); `--vuln-mode` changes nothing for any other image.
VULN_REPORT_ONLY = frozenset(
    {
        "greenmail/standalone",
        "axllent/mailpit",  # D-348: replaced MailHog; GO-2026-5932 (golang.org/x/crypto) in v1.33.1
    }
)
VULN_MODES = ("block", "report")


def report_only(ref: str) -> bool:
    """Is this image (any tag, digest or registry) in the report-mode set?"""
    repo = repository(ref)
    return any(repo == name or repo.endswith("/" + name) for name in VULN_REPORT_ONLY)


def split_report_mode(
    failing: list[vulns.Finding], ref: str, vuln_mode: str
) -> tuple[list[vulns.Finding], list[vulns.Finding]]:
    """(blocking, deferred): only a fixable CRITICAL/HIGH finding of a report-mode image is deferred, in every
    mode (D-827). ``vuln_mode`` is checked by run_gates; it no longer changes the split."""
    if not report_only(ref):
        return list(failing), []
    blocking: list[vulns.Finding] = []
    deferred: list[vulns.Finding] = []
    for f in failing:
        fixable_high = f.severity in ("CRITICAL", "HIGH", vulns.UNSCORED) and bool(f.fixed)
        (deferred if fixable_high else blocking).append(f)
    return blocking, deferred


def finding_row(f: vulns.Finding) -> dict[str, str]:
    return {
        "id": f.id,
        "severity": f.severity,
        "package": f.package,
        "installed": f.version,
        "fixed": f.fixed,
        "target": f.target,
    }


@dataclass(frozen=True)
class Target:
    ref: str
    platform: str | None = None
    remote: bool = False


def parse_target(text: str) -> Target:
    """``REF``, ``REF=os/arch``, or ``registry:REF=os/arch`` for an image in a registry."""
    remote = text.startswith("registry:")
    ref, _, plat = text.removeprefix("registry:").partition("=")
    return Target(ref.strip(), plat.strip() or None, remote)


def repository(ref: str) -> str:
    """``postgres:16-alpine@sha256:..`` -> ``postgres``; ``localhost:5000/x:1`` -> ``localhost:5000/x``."""
    ref = ref.split("@", 1)[0]
    head, _, last = ref.rpartition("/")
    name = last.split(":", 1)[0]
    return f"{head}/{name}" if head else name


def pin_remote(ref: str) -> str:
    """A registry reference by digest: kept when it has one, else the tag's current digest (recorded)."""
    if "@sha256:" in ref:
        return f"{repository(ref)}@sha256:{ref.split('@sha256:', 1)[1]}"
    cmd = ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise vulns.ReportError(f"{ref}: cannot resolve its digest ({proc.stderr.strip()[:200]})")
    digest = str(json.loads(proc.stdout).get("digest", ""))
    if not digest.startswith("sha256:"):
        raise vulns.ReportError(f"{ref}: the registry gave no sha256 digest")
    return f"{repository(ref)}@{digest}"


def inspect_local(ref: str) -> dict[str, Any]:
    """``docker image inspect`` of a local image: Id, RepoDigests and platform."""
    proc = subprocess.run(["docker", "image", "inspect", ref], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise vulns.ReportError(f"{ref}: not a local image ({proc.stderr.strip()[:200]})")
    data = json.loads(proc.stdout)[0]
    plat = f"{data.get('Os', '?')}/{data.get('Architecture', '?')}" + (
        f"/{data['Variant']}" if data.get("Variant") else ""
    )
    return {"image_id": str(data["Id"]), "repo_digests": list(data.get("RepoDigests") or []), "platform": plat}


# D-886: the make target that builds each of our images (every other one: `make images`)
BUILT_BY = {"trialbox-demo": "make demo-bundle"}


def missing_local(targets: list[Target], *, inspect: Callable[[str], dict[str, Any]] | None = None) -> list[str]:
    """Every local image the gates are given and Docker does not have, with the target that builds it: said before
    any scan (lane G's build failed in the scan step on the demo image, which `make images` does not build)."""
    look = inspect or inspect_local
    out = []
    for t in targets:
        if t.remote:
            continue
        try:
            look(t.ref)
        except vulns.ReportError:
            how = BUILT_BY.get(repository(t.ref), "make images")
            out.append(f"{t.ref} is not a local image: build it with `{how}` (or leave it out: SC_OWN_IMAGES)")
    return out


def same_platform(asked: str, got: str) -> bool:
    """``linux/arm64`` matches ``linux/arm64`` and ``linux/arm64/v8``; never ``linux/amd64``."""
    want, have = asked.strip("/").split("/"), got.strip("/").split("/")
    return have[: len(want)] == want


def _digest(ref: str) -> str | None:
    return "sha256:" + ref.split("@sha256:", 1)[1] if "@sha256:" in ref else None


def identity_problems(
    target: Target, pinned: dict[str, Any], report: vulns.TrivyReport, sbom_doc: dict[str, Any]
) -> list[str]:
    """The Trivy report and the SBOM must name the image that was pinned before the scan.

    Trivy reports the image id (config digest), repo digests and layer diff ids. Syft names a registry image by the
    digest it pulled, but a local image only by its tag; so for both, every layer the SBOM found a package in must be
    one of the layers Trivy scanned, and for a registry image the SBOM must also name the digest."""
    sbom_version = sbom.subject_version(sbom_doc)
    layers = sbom.layer_ids(sbom_doc)
    problems: list[str] = []
    if pinned.get("image_id") and report.image_id != pinned["image_id"]:
        problems.append(f"Trivy scanned image {report.image_id or '?'}, not the pinned {pinned['image_id']}")
    digest = _digest(target.ref)
    if digest and not any(d.endswith(digest) for d in report.repo_digests) and report.image_id != digest:
        problems.append(f"Trivy report does not name the digest {digest} (repo digests {list(report.repo_digests)})")
    if target.platform and not same_platform(target.platform, report.platform):
        problems.append(f"Trivy scanned platform {report.platform}, asked for {target.platform}")
    if not layers:
        problems.append("the SBOM names no image layers; it cannot be tied to the scanned image")
    elif not layers <= set(report.diff_ids):
        problems.append(f"the SBOM has {len(layers - set(report.diff_ids))} layers that are not in the scanned image")
    if target.remote:
        names = {report.image_id, *(d.split("@", 1)[-1] for d in report.repo_digests)}
        if digest:
            names.add(digest)
        if sbom_version not in names:
            problems.append(
                f"the SBOM names {sbom_version or '?'}, not the scanned image ({sorted(n for n in names if n)})"
            )
    return problems


def run_gates(
    targets: list[Target],
    *,
    cache_dir: Path,
    out_dir: Path,
    sbom_dir: Path,
    allow: Allowlist,
    allow_errors: list[str],
    lock_sbom: Path | None,
    insecure: bool = False,
    severities: frozenset[str] = vulns.DEFAULT_FAIL_SEVERITIES,
    fail_unfixed: bool = False,
    vuln_mode: str = "block",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Scan and gate every target; return the record (also written to ``out_dir/gates.json``).

    For the images in ``VULN_REPORT_ONLY`` only, in either ``vuln_mode`` (D-827), a fixable CRITICAL/HIGH finding is
    recorded and shown but does not fail the image. Everything else still fails: such findings in any other image,
    a missing or odd severity, an unreadable or empty report, a scan or SBOM that does not name the image."""
    if vuln_mode not in VULN_MODES:
        raise vulns.ReportError(f"vuln mode must be one of {', '.join(VULN_MODES)}, got {vuln_mode!r}")
    now = now or dt.datetime.now(dt.UTC)
    out_dir.mkdir(parents=True, exist_ok=True)
    sbom_dir.mkdir(parents=True, exist_ok=True)
    env, removed = vulns.scanner_env()
    syft_env = sbom.syft_env(env)
    if insecure:  # a plain-HTTP registry on the build machine (the CI's local registry for images-multiarch)
        syft_env["SYFT_REGISTRY_INSECURE_USE_HTTP"] = "true"
    db_errors, db_seen = vulns.db_problems(cache_dir, now)
    record: dict[str, Any] = {
        "created": now.isoformat(),
        "trivy_db": db_seen,
        "removed_env": removed,
        "allowlist_errors": allow_errors,
        "images": [],
    }
    sboms: dict[str, dict[str, Any]] = {}
    index: list[dict[str, Any]] = []
    if lock_sbom is not None:
        if lock_sbom.is_file():
            doc = json.loads(lock_sbom.read_text(encoding="utf-8"))
            sboms[lock_sbom.name] = doc
            index.append(
                {"source": "deploy/requirements.lock", "file": lock_sbom.name, "sha256": sbom.sha256(lock_sbom)}
            )
        else:
            record["lock_sbom_error"] = f"{lock_sbom} is missing (make lock-sbom)"
    fails = vulns.trivy_fails(severities, fail_unfixed)
    for target in targets:
        entry: dict[str, Any] = {"ref": target.ref, "platform": target.platform, "ok": False, "errors": []}
        record["images"].append(entry)
        remote = target.remote
        try:
            if remote:
                if not target.platform:
                    raise vulns.ReportError(f"{target.ref}: a registry image needs a platform (REF=os/arch)")
                entry["requested"] = target.ref
                target = Target(pin_remote(target.ref), target.platform, True)
                entry["ref"] = target.ref
                pinned: dict[str, Any] = {"image_id": None, "repo_digests": [target.ref], "platform": target.platform}
            else:
                pinned = inspect_local(target.ref)
                if target.platform and not same_platform(target.platform, pinned["platform"]):
                    raise vulns.ReportError(f"{target.ref} is {pinned['platform']}, asked for {target.platform}")
            entry.update(image_id=pinned["image_id"], repo_digests=pinned["repo_digests"])
            plat = target.platform or pinned.get("platform")
            report_path = out_dir / sbom.file_name(target.ref, plat).replace(".cdx.json", ".trivy.json")
            cmd = vulns.trivy_command(
                target.ref, cache_dir, report_path, platform=plat if remote else None, remote=remote, insecure=insecure
            )
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise vulns.ReportError(f"trivy failed (exit {proc.returncode}): {proc.stderr.strip()[-300:]}")
            report = vulns.parse_trivy(
                vulns.load_json(report_path),
                vulns.expected_lang_types(target.ref),
                os_unreadable=allow.os_unreadable(target.ref) is not None,
            )
            source = f"registry:{target.ref}" if remote else f"docker:{target.ref}"
            sbom_path = sbom_dir / sbom.file_name(target.ref, plat)
            doc = sbom.run_syft(source, sbom_path, syft_env, platform=plat if remote else None)
            entry["errors"] += identity_problems(target, pinned, report, doc)
            result = vulns.gate(list(report.findings), allow, fails=fails, subject=target.ref)
            blocking, deferred = split_report_mode(result.failing, target.ref, vuln_mode)
            entry.update(
                platform=report.platform,
                image_id=pinned["image_id"] or report.image_id,
                repo_digests=sorted(set(pinned["repo_digests"]) | set(report.repo_digests)),
                trivy_report=report_path.name,
                trivy_sha256=sbom.sha256(report_path),
                sbom=sbom_path.name,
                sbom_sha256=sbom.sha256(sbom_path),
                failing=[f"{f.id} {f.package} {f.version}" for f in blocking],
                failing_detail=[finding_row(f) for f in blocking],
                vuln_mode="report" if report_only(target.ref) else "block",
                report_mode_findings=[finding_row(f) for f in deferred],
                accepted=[f"{f.id} {f.package}: {why}" for f, why in result.accepted],
                reported=len(result.reported),
            )
            entry["ok"] = not blocking and not result.errors and not entry["errors"]
            sboms[sbom_path.name] = doc
            index.append(
                {
                    "source": target.ref,
                    "platform": report.platform,
                    "image_id": entry["image_id"],
                    "repo_digests": entry["repo_digests"],
                    "file": sbom_path.name,
                    "sha256": entry["sbom_sha256"],
                }
            )
        except (vulns.ReportError, sbom.SbomError, OSError, json.JSONDecodeError) as exc:
            entry["errors"].append(str(exc))
    lic = licences.evaluate(sboms, allow)
    (sbom_dir / "licences.md").write_text(licences.render(lic), encoding="utf-8")
    record["licences"] = {
        "ok": lic.ok,
        "failing": [f"{r.package} {r.version} ({subj}): {', '.join(sorted(r.open_flags))}" for r, subj in lic.failing],
        "budgets": [
            {"image": b.subject, "ecosystem": b.ecosystem, "open": b.count, "max": b.max, "ok": b.ok}
            for b in lic.budgets
        ],
        "report": "licences.md",
    }
    record["db_errors"] = db_errors
    record["ok"] = bool(
        targets
        and all(e["ok"] for e in record["images"])
        and record["licences"]["ok"]
        and not db_errors
        and not allow_errors
        and "lock_sbom_error" not in record
    )
    (sbom_dir / "index.json").write_text(json.dumps({"sboms": index}, indent=2) + "\n", encoding="utf-8")
    record["vuln_mode"] = vuln_mode
    (out_dir / "gates.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_markdown(record), encoding="utf-8")
    return record


def summary_markdown(record: dict[str, Any]) -> str:
    """The CI job summary: the result per image and platform, and every CRITICAL/HIGH finding, blocking or reported."""
    mode = record.get("vuln_mode", "block")
    out = [
        f"## Release gates: {'PASS' if record.get('ok') else 'FAIL'}",
        "",
        f"Image vulnerability gate mode: **{mode}**"
        + (
            " (fixable CRITICAL/HIGH findings in the test-only images "
            + ", ".join(sorted(VULN_REPORT_ONLY))
            + " are reported, not blocking, in every mode (D-827); no bundle carries them; see"
            " deploy/security/known-image-findings.md)"
        ),
        "",
        "| Image | Platform | Result | Blocking findings | Reported findings | Errors |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in record.get("images", []):
        out.append(
            f"| {e.get('ref')} | {e.get('platform') or '?'} | {'PASS' if e.get('ok') else 'FAIL'} | "
            f"{len(e.get('failing_detail', []))} | {len(e.get('report_mode_findings', []))} | "
            f"{'; '.join(e.get('errors', []))[:200].replace('|', '/')} |"
        )
    lic = record.get("licences", {})
    out += ["", f"Licence gate: **{'PASS' if lic.get('ok') else 'FAIL'}** ({len(lic.get('failing', []))} failing)"]
    out += [f"- {x}" for x in lic.get("failing", [])]
    for e in record.get("images", []):
        rows = [("blocking", x) for x in e.get("failing_detail", [])]
        rows += [("reported", x) for x in e.get("report_mode_findings", [])]
        if not rows:
            continue
        out += ["", f"### {e.get('ref')} ({e.get('platform') or '?'})", ""]
        out += ["| Gate | CVE | Severity | Package | Installed | Fixed in |", "| --- | --- | --- | --- | --- | --- |"]
        for kind, x in rows:
            out.append(
                f"| {kind} | {x['id']} | {x['severity']} | {x['package']} | {x['installed']} | {x['fixed'] or '-'} |"
            )
    return "\n".join(out) + "\n"


def render(record: dict[str, Any]) -> str:
    lines = [f"release gates: {'PASS' if record.get('ok') else 'FAIL'}"]
    lines += [f"  ERROR {e}" for e in record.get("db_errors", [])]
    lines += [f"  ERROR allow-list: {e}" for e in record.get("allowlist_errors", [])]
    if record.get("lock_sbom_error"):
        lines.append(f"  ERROR {record['lock_sbom_error']}")
    if record.get("removed_env"):
        lines.append(f"  note  ignored environment: {', '.join(record['removed_env'])}")
    for e in record.get("images", []):
        state = "PASS" if e.get("ok") else "FAIL"
        lines.append(f"  {state}  {e['ref']} {e.get('platform') or ''} {e.get('image_id') or ''}".rstrip())
        lines += [f"        ERROR {x}" for x in e.get("errors", [])]
        lines += [f"        FAIL  {x}" for x in e.get("failing", [])]
        lines += [
            f"        REPORT {x['id']} {x['severity']} {x['package']} {x['installed']} (fixed in {x['fixed']})"
            for x in e.get("report_mode_findings", [])
        ]
    lic = record.get("licences", {})
    lines.append(f"  {'PASS' if lic.get('ok') else 'FAIL'}  licences ({lic.get('report')})")
    lines += [f"        FAIL  {x}" for x in lic.get("failing", [])]
    for b in lic.get("budgets", []):
        state = "ok  " if b["ok"] else "FAIL"
        lines.append(f"        {state}  budget {b['image']} {b['ecosystem']}: {b['open']} open, budget {b['max']}")
    return "\n".join(lines)


def bundle_problems(
    record: Any,
    images: Mapping[str, str | tuple[str, ...]],
    *,
    now: dt.datetime | None = None,
    platforms: Mapping[str, str] | None = None,
) -> list[str]:
    """Images (ref -> local image id, or every digest that names the image) a bundle may not carry under this
    record (passing, and at most ``vulns.MAX_DB_AGE_DAYS`` old: a newer advisory may have arrived since).

    D-830: with ``platforms`` (ref -> the local image's platform), a digest also matches a passing entry's repo
    digest (the index a registry image was pinned by before its scan) on that entry's platform only: on the
    containerd store a pulled image's Id is its index digest, while the gates record its config digest."""
    if not isinstance(record, dict) or not record.get("ok"):
        return ["the gate record did not pass (or is not a gate record)"]
    created = vulns.parse_time(record.get("created"))
    now = now or dt.datetime.now(dt.UTC)
    if created is None or now - created > dt.timedelta(days=vulns.MAX_DB_AGE_DAYS):
        return [f"the gate record is older than {vulns.MAX_DB_AGE_DAYS} days (or undated); run make release-gates"]
    # matched by image id (config digest): the content itself, whatever tag or registry it came under
    # an image that passed only because its findings were in report mode is not releasable
    passed = {
        e.get("image_id")
        for e in record.get("images", [])
        if e.get("ok") and e.get("image_id") and not e.get("report_mode_findings")
    }
    by_index: dict[str, list[str]] = {}  # repo digest -> the platforms it passed on (D-830)
    for e in record.get("images", []):
        if e.get("ok") and e.get("image_id") and not e.get("report_mode_findings"):
            for rd in e.get("repo_digests") or []:
                by_index.setdefault(str(rd).rsplit("@", 1)[-1], []).append(str(e.get("platform") or ""))
    problems = []
    for ref, image_id in images.items():
        ids = (image_id,) if isinstance(image_id, str) else tuple(image_id)
        plat = (platforms or {}).get(ref, "")
        on_index = bool(plat) and any(
            i.startswith("sha256:") and same_platform(plat, p) for i in ids if i for p in by_index.get(i, [])
        )
        if not on_index and not any(i and i in passed for i in ids):  # D-570: the id differs by image store
            problems.append(
                f"{ref} ({ids[0] if ids else ''}) is not a passing image of this record; run make release-gates"
            )
    return problems
