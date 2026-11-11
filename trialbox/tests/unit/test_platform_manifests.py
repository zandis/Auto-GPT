"""The platform deployment (WS-14.8, WS-11.8, WS-13.9; D-211): the Kubernetes manifests of ``deploy/platform``, the
``shared-quota`` profile, ``trialbox doctor --platform`` and the egress allowlist rendered as a NetworkPolicy.

Done-when (T-113): the overlays build and validate (with ``kustomize`` and ``kubeconform`` when they are installed,
and always by the structural check here); the rendered manifests carry ``release.json``'s digests; a ``latest`` tag
is refused; the NetworkPolicy names the same hosts as the nftables table; ``doctor --platform`` fails on a missing
NetworkPolicy, a quota under the profile's minimum and a Secret holding the KEK, and reports the GPU checks as
``skipped: no device`` with ``--no-gpu`` (refused in VALIDATION and PRODUCTION); the shared-quota serving values are
never defaulted. The review fixes of 2026-11-10 (D-211) each have a test below, named after what they refuse.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.trialbox import doctor
from tools.trialbox import platform as pf
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "deploy" / "platform"
OVERLAYS = ("shared-quota", "interim-cloud")
DIGEST = "sha256:" + "cd" * 32
# what the platform team creates before the first apply (RUNBOOK §17), never committed
PROVIDED = {
    "Secret": {"trialbox-db", "trialbox-mail", "trialbox-cloud", "trialbox-actor"}
    | {f"trialbox-token-{s}" for s in ("lake", "embed-service", "doc-parser", "criteria-compiler", "adapter")}
    | {f"trialbox-token-{s}" for s in ("orchestrator", "mail-gateway", "gateway", "console")},
    "ConfigMap": {"trialbox-service-tokens", "trialbox-site", "trialbox-serving-record"},
}


# ------------------------------------------------------------------------------------------------ a small build
class _Loader(yaml.SafeLoader):
    """Compose files use ``!override`` / ``!reset``; read them as plain values."""


def _override(ld: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return ld.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return ld.construct_mapping(node, deep=True)
    return ld.construct_scalar(node)  # type: ignore[arg-type]


_Loader.add_constructor("!override", _override)
_Loader.add_constructor("!reset", lambda ld, node: None)


def _kustomization(d: Path) -> dict[str, Any]:
    return yaml.safe_load((d / "kustomization.yaml").read_text(encoding="utf-8")) or {}


def _generated(d: Path, k: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for g in k.get("configMapGenerator") or []:
        data: dict[str, str] = {}
        for f in g.get("files") or []:
            key, _, src = f.partition("=")
            data[key if src else Path(key).name] = (d / (src or key)).read_text(encoding="utf-8")
        for e in g.get("envs") or []:
            for line in (d / e).read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    kk, _, vv = line.partition("=")
                    data[kk] = vv
        for lit in g.get("literals") or []:
            kk, _, vv = lit.partition("=")
            data[kk] = vv
        out.append(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": g["name"]},
                "data": data,
                "_behavior": g.get("behavior"),
            }
        )
    return out


def build(overlay: str) -> list[dict[str, Any]]:
    """A pure-Python stand-in for ``kustomize build`` of these overlays (resources, components, configMapGenerator
    with merge, the images transformer): enough to check what this test needs when kustomize is not installed."""
    objs: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    def load(d: Path) -> None:
        k = _kustomization(d)
        for r in k.get("resources") or []:
            p = d / r
            if p.is_dir():
                load(p)
            else:
                objs.extend(x for x in yaml.safe_load_all(p.read_text(encoding="utf-8")) if x)
        for c in k.get("components") or []:
            load(d / c)
        for cm in _generated(d, k):
            behavior = cm.pop("_behavior")
            old = next(
                (o for o in objs if o["kind"] == "ConfigMap" and o["metadata"]["name"] == cm["metadata"]["name"]), None
            )
            if behavior == "merge":
                assert old is not None, f"{d}: merge into a missing ConfigMap {cm['metadata']['name']}"
                old["data"].update(cm["data"])
            else:
                assert old is None, f"{d}: ConfigMap {cm['metadata']['name']} generated twice"
                objs.append(cm)
        images.extend(k.get("images") or [])

    load(PLATFORM / "overlays" / overlay)
    by_name = {i["name"]: i for i in images}
    for _, spec, _ in pf.pod_specs(pf.PlatformState(objs)):
        for c in pf.containers(spec):
            i = by_name.get(c["image"])
            if i:
                c["image"] = i["newName"] + (f"@{i['digest']}" if i.get("digest") else f":{i['newTag']}")
    return objs


def _rendered(overlay: str) -> str:
    """``kustomize build`` when installed (TB_KUSTOMIZE or PATH), else the stand-in."""
    exe = os.environ.get("TB_KUSTOMIZE") or shutil.which("kustomize")
    if exe:
        out = subprocess.run(
            [exe, "build", str(PLATFORM / "overlays" / overlay)], check=True, capture_output=True, text=True
        )
        return out.stdout
    return yaml.safe_dump_all(build(overlay), sort_keys=False)


# ------------------------------------------------------------------------------------------------ manifests
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_overlay_builds_and_is_consistent(overlay: str) -> None:
    """Structural validation without a cluster: every object has apiVersion/kind/name, names are unique per kind,
    every Service and NetworkPolicy selects a workload that exists, every ConfigMap, Secret and claim a pod uses is
    defined here or is one the platform team provides (RUNBOOK §17), and every pod is non-privileged."""
    objs = build(overlay)
    seen: set[tuple[str, str]] = set()
    for o in objs:
        assert o.get("apiVersion") and o.get("kind") and o["metadata"].get("name"), o
        key = (o["kind"], o["metadata"]["name"])
        assert key not in seen, f"duplicate {key}"
        seen.add(key)
    st = pf.PlatformState(objs)
    labels = [
        ((spec_owner.get("spec") or {}).get("template") or {}).get("metadata", {}).get("labels", {})
        for spec_owner in st.of("Deployment", "StatefulSet", "Job")
    ]
    components = {lab.get("app.kubernetes.io/component") for lab in labels}
    for svc in st.of("Service"):
        assert svc["spec"]["selector"]["app.kubernetes.io/component"] in components, svc["metadata"]["name"]
    for wl in st.of("Deployment", "StatefulSet"):
        sel = wl["spec"]["selector"]["matchLabels"]
        assert sel.items() <= wl["spec"]["template"]["metadata"]["labels"].items(), wl["metadata"]["name"]
    for pol in st.of("NetworkPolicy"):
        comp = (pol["spec"]["podSelector"].get("matchLabels") or {}).get("app.kubernetes.io/component")
        assert comp is None or comp in components, pol["metadata"]["name"]
    defined = {
        "ConfigMap": {n for k, n in seen if k == "ConfigMap"},
        "Secret": set(),
        "PersistentVolumeClaim": {n for k, n in seen if k == "PersistentVolumeClaim"},
    }
    for owner, spec, _ in pf.pod_specs(st):
        assert spec.get("securityContext", {}).get("seccompProfile") == {"type": "RuntimeDefault"}, pf._name(owner)
        for v in spec.get("volumes") or []:
            if "configMap" in v:
                n = v["configMap"]["name"]
                assert n in defined["ConfigMap"] or n in PROVIDED["ConfigMap"], (pf._name(owner), n)
            if "secret" in v:
                assert v["secret"]["secretName"] in PROVIDED["Secret"], (pf._name(owner), v)
            if "persistentVolumeClaim" in v:
                assert v["persistentVolumeClaim"]["claimName"] in defined["PersistentVolumeClaim"], (pf._name(owner), v)
        for c in pf.containers(spec):
            sc = c.get("securityContext") or {}
            assert sc.get("allowPrivilegeEscalation") is False and sc.get("capabilities") == {"drop": ["ALL"]}, c[
                "name"
            ]
            assert "privileged" not in sc and not spec.get("hostNetwork") and not spec.get("hostPID")
            for ref in c.get("envFrom") or []:
                n = ref.get("configMapRef", {}).get("name")
                assert n is None or n in defined["ConfigMap"] or ref["configMapRef"].get("optional"), n
            for e in c.get("env") or []:
                sk = (e.get("valueFrom") or {}).get("secretKeyRef")
                assert sk is None or sk["name"] in PROVIDED["Secret"], sk
    # the pair profile env, as install.sh writes it for a pair (D-142), and the profile's name for the gateway
    env = next(o for o in objs if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "trialbox-env")["data"]
    assert env["TB_GATEWAY_VERIFIER_MODEL"] == "v-verifier" and env["TB_LLM_MODE"] == "vllm"
    assert env["TB_PROFILE"] == {"shared-quota": "P-SHARED-QUOTA", "interim-cloud": "P-INTERIM-CLOUD"}[overlay]


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_kustomize_build_validates_with_kubeconform(overlay: str) -> None:
    """Acceptance (1): ``kustomize build deploy/platform/overlays/<overlay> | kubeconform -strict``. Runs where both
    binaries are installed (TB_KUSTOMIZE / TB_KUBECONFORM or PATH; pinned versions in RUNBOOK §17)."""
    kz = os.environ.get("TB_KUSTOMIZE") or shutil.which("kustomize")
    kc = os.environ.get("TB_KUBECONFORM") or shutil.which("kubeconform")
    if not (kz and kc):
        pytest.skip("kustomize and kubeconform not installed (the structural test above still ran)")
    text = _rendered(overlay)
    args = [kc, "-strict", "-summary", "-kubernetes-version", "1.31.0"]
    if os.environ.get("TB_KUBECONFORM_CACHE"):
        args += ["-cache", os.environ["TB_KUBECONFORM_CACHE"]]
    out = subprocess.run([*args, "-"], input=text, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "Invalid: 0, Errors: 0" in out.stdout


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_rendered_manifests_carry_the_release_digests(overlay: str) -> None:
    """Acceptance (5): the release-images component is generated from release.json and every image of the build is
    the release's: by digest where the release has one, by its tag only while it is unreleased."""
    assert pf.component_matches(), "run `python -m tools.trialbox platform-images` and commit the result"
    rel = pf.load_release()
    st = pf.state_from_manifests(_rendered(overlay))
    used = set()
    for _, spec, _ in pf.pod_specs(st):
        for c in pf.containers(spec):
            repo, tag, digest = pf.split_ref(c["image"])
            img = rel.by_repository(repo)
            assert img is not None, c["image"]
            used.add(img.name)
            assert (digest, tag) == ((img.digest, None) if img.digest else (None, img.tag)), c["image"]
    assert used == set(rel.images)  # every release image is used, none is extra
    assert any(i.digest for i in rel.images.values())


def test_a_release_with_other_digests_regenerates_the_component(tmp_path: Path) -> None:
    rel = json.loads(pf.RELEASE.read_text(encoding="utf-8"))
    for name in ("trialbox-py", "trialbox-jvm", "vllm", "trialbox-postgres"):
        rel["images"][name]["digest"] = DIGEST
    p = tmp_path / "release.json"
    p.write_text(json.dumps(rel), encoding="utf-8")
    assert not pf.component_matches(p)
    out = tmp_path / "c" / "kustomization.yaml"
    pf.write_component(p, out)
    comp = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert {i["name"]: i.get("digest") for i in comp["images"]}["trialbox-py"] == DIGEST
    assert all("newTag" not in i for i in comp["images"])
    assert pf.component_matches(p, out)
    assert f"TB_JVM_IMAGE=trialbox-jvm:1.0.0@{DIGEST}" in pf.compose_env(pf.load_release(p))


def test_a_latest_tag_is_refused() -> None:
    """A manifest with ``latest`` (or no tag at all) is refused by the lint, by doctor and in release.json."""
    good = _rendered("shared-quota")
    assert pf.lint_manifests(good) == []
    bad = good.replace("image: trialbox-py:1.0.0", "image: trialbox-py:latest", 1)
    assert bad != good
    refused = pf.lint_manifests(bad)
    assert len(refused) == 1 and "trialbox-py:latest" in refused[0]
    assert pf.lint_manifests(good.replace("image: trialbox-jvm:1.0.0", "image: trialbox-jvm", 1))
    c = pf.check_image_digests(_inputs(pf.state_from_manifests(bad)))
    assert c.status == "FAIL" and "latest" in c.detail
    rel = json.loads(pf.RELEASE.read_text(encoding="utf-8"))
    rel["images"]["vllm"]["image"] = "vllm/vllm-openai:latest"
    with pytest.raises(pf.PlatformError, match="latest"):
        pf.load_release(_write(rel))


def test_copies_in_the_base_are_byte_identical() -> None:
    """kustomize reads files only under the kustomization, so the base carries two copies; they never drift."""
    base = PLATFORM / "base"
    assert (base / "settings.example.yaml").read_bytes() == (ROOT / "deploy/settings.example.yaml").read_bytes()
    for f in ("10-trialbox-wf.sh", "20-extensions.sh", "30-service-roles.sh"):
        assert (base / "db-init" / f).read_bytes() == (ROOT / "deploy/docker/db-init" / f).read_bytes(), f


def test_platform_db_is_the_d204_image() -> None:
    """Review fix 1 (D-204 came in with the master merge): the platform forms run the box's database image
    (``trialbox-postgres:16-1``, pgvector and PGroonga), not stock postgres: the release entry is the lock's image and
    digest, the StatefulSet runs it as the Debian image's uid, every db-init script of the appliance (the extensions
    too) is in the ConfigMap, the readiness probe is the image's ``tb-db-check``, and the compose platform form's
    POSTGRES_IMAGE comes from the same entry."""
    lock = json.loads((ROOT / "deploy/images.lock").read_text(encoding="utf-8"))["images"]["db"]
    rel = pf.load_release()
    img = rel.images["trialbox-postgres"]
    assert (img.image, img.digest) == (lock["image"], lock["digest"])
    assert not any(i.repository == "postgres" for i in rel.images.values())
    assert dict(line.split("=", 1) for line in pf.compose_env(rel))["POSTGRES_IMAGE"].startswith(lock["image"])
    dockerfile = (ROOT / "deploy/docker/db.Dockerfile").read_text(encoding="utf-8")
    base_ref = re.search(r"^ARG POSTGRES_BASE=(\S+)", dockerfile, re.M)
    assert base_ref and base_ref.group(1).startswith("postgres:16-trixie@")  # Debian: postgres is uid/gid 999
    assert "alpine" not in base_ref.group(1) and not re.search(r"^USER ", dockerfile, re.M)
    sts = next(o for o in build("shared-quota") if o["kind"] == "StatefulSet" and o["metadata"]["name"] == "db")
    pod = sts["spec"]["template"]["spec"]
    sc = pod["securityContext"]
    assert (sc["runAsUser"], sc["runAsGroup"], sc["fsGroup"]) == (999, 999, 999)
    c = pod["containers"][0]
    assert c["image"] == "trialbox-postgres:16-1"  # by tag while the lock's digest is null (T-110 releases it)
    assert c["readinessProbe"]["exec"]["command"] == [Path(lock["healthcheck"]).name]
    assert "COPY --chmod=0755 db.healthcheck.sh " + lock["healthcheck"] in dockerfile
    gen = next(g for g in _kustomization(PLATFORM / "base")["configMapGenerator"] if g["name"] == "trialbox-db-init")
    shipped = sorted(p.name for p in (ROOT / "deploy/docker/db-init").iterdir() if p.suffix == ".sh")
    assert sorted(Path(f).name for f in gen["files"]) == shipped
    assert "20-extensions.sh" in shipped


# ------------------------------------------------------------------------------------------------ shared-quota
SERVING_VARS = (
    "JUDGE_MAX_LEN",
    "JUDGE_MAX_SEQS",
    "JUDGE_GPU_MEM_UTIL",
    "VERIFIER_MAX_LEN",
    "VERIFIER_MAX_SEQS",
    "VERIFIER_GPU_MEM_UTIL",
    "TB_MIG_JUDGE_DEVICE",
    "TB_MIG_VERIFIER_DEVICE",
    "TB_MIG_PROFILE",
)


def test_shared_quota_serving_values_are_never_defaulted() -> None:
    """Measured, never assumed: the compose profile has no default for any serving value (compose refuses to start
    without them) and the Kubernetes overlays read `unmeasured` until the serving record exists (T-114)."""
    text = (ROOT / "deploy/docker-compose.shared-quota.yml").read_text(encoding="utf-8")
    for var in SERVING_VARS:
        uses = re.findall(r"\$\{" + var + r"(:?[-?][^}]*)?\}", text)
        assert uses and all(u.startswith(":?") for u in uses), (var, uses)
    doc = yaml.load(text, Loader=_Loader)
    for role, dev in (("llm-service", "TB_MIG_JUDGE_DEVICE"), ("llm-verifier", "TB_MIG_VERIFIER_DEVICE")):
        devs = doc["services"][role]["deploy"]["resources"]["reservations"]["devices"]
        assert len(devs) == 1 and dev in devs[0]["device_ids"][0] and "count" not in devs[0]
    assert "!override" in text  # the base llm-service's `count: 1` is replaced, not added to
    for overlay in OVERLAYS:
        env = dict(
            line.split("=", 1)
            for line in (PLATFORM / "overlays" / overlay / "serving.env").read_text(encoding="utf-8").split()
        )
        assert {k: v for k, v in env.items() if k.endswith(("_LEN", "_SEQS", "_UTIL"))} == dict.fromkeys(
            [k for k in env if k.endswith(("_LEN", "_SEQS", "_UTIL"))], "unmeasured"
        )
    gpu = [
        o
        for o in build("shared-quota")
        if o["kind"] == "Deployment" and o["metadata"]["labels"].get("trialbox.io/tier") == "model"
    ]
    assert len(gpu) == 2
    for d in gpu:
        c = d["spec"]["template"]["spec"]["containers"][0]
        assert c["resources"]["limits"]["nvidia.com/gpu"] == 1  # one device (a MIG instance) per server
        assert any(a.startswith("--max-model-len=$(") for a in c["args"])


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker compose not installed")
def test_compose_refuses_the_shared_quota_profile_unmeasured(tmp_path: Path) -> None:
    d = tmp_path / "deploy"
    shutil.copytree(
        ROOT / "deploy", d, ignore=shutil.ignore_patterns("models", "refdata", "measured", "gcp", "windows", "secrets")
    )
    (d / ".env").write_text("POSTGRES_PASSWORD=x\n", encoding="utf-8")
    args = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.shared-quota.yml",
        "--profile",
        "gpu",
        "config",
        "-q",
    ]
    env = {k: v for k, v in os.environ.items() if k not in SERVING_VARS}
    # the partition's MIG profile and instances are given (compose names the first missing value in no fixed order),
    # so the only missing values are the measured serving ones
    env.update(TB_MIG_PROFILE="1g.24gb", TB_MIG_JUDGE_DEVICE="MIG-judge", TB_MIG_VERIFIER_DEVICE="MIG-verifier")
    out = subprocess.run(args, cwd=d, capture_output=True, text=True, check=False, env=env)
    if "is not a docker command" in out.stderr or "unknown command" in out.stderr:
        pytest.skip("docker compose plugin missing")
    assert out.returncode != 0 and "measured on the partition" in out.stderr + out.stdout


@pytest.mark.parametrize(
    ("mig", "card", "profile"),
    [
        ("Enabled", "NVIDIA B200", "shared-quota"),
        ("Disabled", "NVIDIA B200", "default"),
        ("[N/A]", "NVIDIA RTX PRO 6000 Blackwell Server Edition", "rtxpro6000"),
    ],
)
def test_gpu_profile_names_a_mig_card_shared_quota(mig: str, card: str, profile: str) -> None:
    out = subprocess.run(
        ["sh", str(ROOT / "deploy/gpu_profile.sh"), "x86_64", card, mig], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == profile


# ------------------------------------------------------------------------------------------------ egress
def test_networkpolicy_names_the_same_hosts_as_nftables() -> None:
    """Acceptance (4): one allowlist (deploy/egress.py), two renderings; the hosts, ports, services and addresses
    are the same in the nftables table and in the NetworkPolicies."""
    eg = doctor._egress()
    env = {
        "SMTP_HOST": "smtp.hospa.test",
        "IMAP_HOST": "imap.hospa.test",
        "NHI_TWPAS_BASE_URL": "https://twpas.nhi.example:8443/api",
        "TB_CTGOV_MODE": "live",
        "CLOUD_LLM_BASE_URL": "https://llm.example.com/v1",
        "EGRESS_EXTRA": "adapter=10.1.2.3:1433",
        "TB_ENV": "PRODUCTION",
    }
    allows = eg.allowlist(env)
    resolver = _dns
    box = eg.Box(subnets=["172.18.0.0/16"], addresses={a.service: ["172.18.0.2", "fd00::2"] for a in allows})
    script, w1 = eg.render(box, allows, resolver)
    pols, w2 = eg.render_networkpolicy(allows, resolver)
    assert not w1 and not w2
    nft = set(re.findall(r'comment "([a-z-]+) -> ([^:]+):(\d+) ', script))
    k8s = {
        (p["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/component"], *hp.rsplit(":", 1))
        for p in pols
        for hp in p["metadata"]["annotations"]["trialbox.io/egress-hosts"].split(",")
    }
    assert nft == k8s == {(a.service, a.host, str(a.port)) for a in allows}
    assert len(k8s) == 6
    nft_addrs = set(re.findall(r"daddr \{ ([^}]+) \} tcp dport (\d+)", script))
    k8s_addrs = {
        (b["ipBlock"]["cidr"].rsplit("/", 1)[0], str(r["ports"][0]["port"]))
        for p in pols
        for r in p["spec"]["egress"]
        for b in r["to"]
    }
    flat = {(a.strip(), port) for addrs, port in nft_addrs for a in addrs.split(",")}
    assert flat == k8s_addrs
    # an unresolvable host: no rule in either, a warning in both (fail closed)
    _, w3 = eg.render_networkpolicy([eg.Allow("mail-gateway", "nowhere.invalid", 25, "x")], lambda h: [])
    assert w3 and "does not resolve" in w3[0]
    # and the doctor compares the rendered policies with the allowlist
    st = pf.PlatformState([*_base_policies(), *pols], "cluster")
    assert pf.check_network_policy(_inputs(st, False, **env)).status == "PASS"
    st2 = pf.PlatformState([*_base_policies(), *pols[1:]], "cluster")
    c = pf.check_network_policy(_inputs(st2, False, **env))
    assert c.status == "FAIL" and "missing" in c.detail


def test_platform_egress_command_prints_policies(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    envf = tmp_path / "site.env"
    envf.write_text("EGRESS_EXTRA=adapter=10.1.2.3:1433\n", encoding="utf-8")
    assert cli(["platform-egress", "--env-file", str(envf)]) == 0
    docs = list(yaml.safe_load_all(capsys.readouterr().out))
    # the gateway's policy holds the model endpoints of the shipped routing (master, D-177); the extra is the adapter's
    by_name = {d["metadata"]["name"]: d for d in docs}
    assert set(by_name) <= {"trialbox-egress-adapter", "trialbox-egress-gateway"}
    assert by_name["trialbox-egress-adapter"]["spec"]["egress"][0]["to"] == [{"ipBlock": {"cidr": "10.1.2.3/32"}}]


# ------------------------------------------------------------------------------------------------ doctor --platform
def _write(doc: dict[str, Any]) -> Path:
    import tempfile

    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    Path(name).write_text(json.dumps(doc), encoding="utf-8")
    return Path(name)


DNS = {
    "smtp.hospa.test": ["10.0.0.25", "2001:db8::25"],
    "imap.hospa.test": ["10.0.0.26"],
    "twpas.nhi.example": ["203.0.113.10"],
    "clinicaltrials.gov": ["130.14.1.1"],
    "llm.example.com": ["198.51.100.8"],
    "ntp.hospa.test": ["10.0.0.123"],
    "ad.hospa.test": ["10.0.0.40"],
    "nas.hospa.test": ["10.0.0.50"],
}


def _dns(h: str) -> list[str]:
    return DNS.get(h, [h] if re.fullmatch(r"[\d.]+", h) else [])


def _inputs(state: pf.PlatformState, no_gpu: bool = False, **env: str) -> pf.PlatformInputs:
    return pf.PlatformInputs(
        state,
        pf.load_release(),
        {"TB_ENV": "TEST", **env},  # TEST: no DEV-only bake-off endpoint in the egress allowlist
        no_gpu=no_gpu,
        connect=lambda h, p: None,
        sntp=lambda s: 0.01,
        resolve=_dns,
    )


def _base_policies() -> list[dict[str, Any]]:
    return [o for o in build("shared-quota") if o["kind"] == "NetworkPolicy"]


def _cluster(objs: list[dict[str, Any]] | None = None, *, quota: dict[str, str] | None = None) -> pf.PlatformState:
    objs = copy.deepcopy(objs if objs is not None else build("shared-quota"))
    if quota is not None:
        objs.append({"kind": "ResourceQuota", "metadata": {"name": "trialbox"}, "spec": {"hard": quota}})
    return pf.PlatformState(objs, "cluster", "trialbox")


ENOUGH = {"requests.cpu": "16", "requests.memory": "96Gi", "requests.nvidia.com/gpu": "2"}


def test_missing_networkpolicy_fails_doctor() -> None:
    st = _cluster(quota=ENOUGH)
    assert pf.check_network_policy(_inputs(st)).status == "PASS"
    st.objects = [
        o for o in st.objects if (o["kind"], o["metadata"]["name"]) != ("NetworkPolicy", "trialbox-default-deny")
    ]
    c = pf.check_network_policy(_inputs(st))
    assert c.status == "FAIL" and "trialbox-default-deny" in c.detail
    # a "default deny" that allows something is not one
    st2 = _cluster(quota=ENOUGH)
    deny = st2.named("NetworkPolicy", "trialbox-default-deny")
    assert deny is not None
    deny["spec"]["egress"] = [{}]
    assert pf.check_network_policy(_inputs(st2)).status == "FAIL"
    # no policy at all
    st3 = pf.PlatformState([o for o in st.objects if o["kind"] != "NetworkPolicy"], "cluster")
    assert pf.check_network_policy(_inputs(st3)).status == "FAIL"


def test_quota_smaller_than_the_profile_minimum_fails_doctor() -> None:
    need = pf.minimum(_cluster())
    assert need["gpu"] == 2  # judge and verifier, one device each
    assert pf.check_quota(_inputs(_cluster(quota=ENOUGH))).status == "PASS"
    small = {**ENOUGH, "requests.nvidia.com/gpu": "1"}
    c = pf.check_quota(_inputs(_cluster(quota=small)))
    assert c.status == "FAIL" and "gpu: quota 1 < profile minimum 2" in c.detail
    c = pf.check_quota(_inputs(_cluster(quota={**ENOUGH, "requests.memory": "8Gi"})))
    assert c.status == "FAIL" and "memory" in c.detail
    c = pf.check_quota(_inputs(_cluster()))
    assert c.status == "FAIL" and "no ResourceQuota" in c.detail and "gpu 2" in c.detail
    # MIG mixed strategy: the resource is named after the profile
    mixed = {"requests.cpu": "16", "requests.memory": "96Gi", "requests.nvidia.com/mig-3g.90gb": "2"}
    assert pf.check_quota(_inputs(_cluster(quota=mixed))).status == "PASS"
    # --no-gpu: the GPU part is skipped, CPU and memory still count
    c = pf.check_quota(_inputs(_cluster(quota=small), no_gpu=True))
    assert c.status == "PASS" and pf.NO_DEVICE in c.detail


def test_a_secret_holding_the_kek_fails_doctor() -> None:
    """Negative (WS-13.11): the KEK, or a key it protects, is never a plain platform Secret (T-210 adds the unseal)."""
    base = _cluster(quota=ENOUGH)
    base.objects.append(
        {"kind": "Secret", "metadata": {"name": "trialbox-db"}, "data": {"POSTGRES_PASSWORD": "", "TB_DB_URL": ""}}
    )
    assert pf.check_kek_custody(_inputs(base)).status == "PASS"
    secrets: list[dict[str, Any]] = [
        {"kind": "Secret", "metadata": {"name": "trialbox-keys"}, "data": {"kek": "c2VjcmV0"}},
        {"kind": "Secret", "metadata": {"name": "trialbox-pidmap"}, "data": {"pid_map.key": "c2VjcmV0"}},
        {"kind": "Secret", "metadata": {"name": "site"}, "stringData": {"site_hmac.key": "x"}},
        {"kind": "Secret", "metadata": {"name": "trialbox-kek"}, "data": {"value": "x"}},
    ]
    for secret in secrets:
        st = _cluster(quota=ENOUGH)
        st.objects.append(secret)
        c = pf.check_kek_custody(_inputs(st))
        assert c.status == "FAIL" and secret["metadata"]["name"] in c.detail, secret
        assert "c2VjcmV0" not in c.detail  # a value is never echoed


def test_image_digests_against_the_release() -> None:
    st = pf.state_from_manifests(_rendered("shared-quota"))
    assert pf.check_image_digests(_inputs(st)).status == "WARN"  # unreleased images, tag only, in TEST
    assert pf.check_image_digests(_inputs(st, TB_ENV="PRODUCTION")).status == "FAIL"
    rel = json.loads(pf.RELEASE.read_text(encoding="utf-8"))
    for v in rel["images"].values():
        v["digest"] = v["digest"] or DIGEST
    released = pf.load_release(_write(rel))
    text = _rendered("shared-quota")
    for ref in ("trialbox-py:1.0.0", "trialbox-jvm:1.0.0", "vllm/vllm-openai:v0.32.0", "trialbox-postgres:16-1"):
        text = text.replace(f"image: {ref}", f"image: {pf.split_ref(ref)[0]}@{DIGEST}")
    inp = _inputs(pf.state_from_manifests(text), TB_ENV="PRODUCTION")
    inp.release = released
    assert pf.check_image_digests(inp).status == "PASS"
    # a pod running another digest than the release
    pod = {
        "kind": "Pod",
        "metadata": {"name": "lake-x", "ownerReferences": [{"kind": "ReplicaSet"}]},
        "status": {
            "containerStatuses": [
                {
                    "name": "lake",
                    "image": "trialbox-py@" + DIGEST,
                    "imageID": "docker.io/trialbox-py@sha256:" + "ee" * 32,
                }
            ]
        },
    }
    inp.state.objects.append(pod)
    c = pf.check_image_digests(inp)
    assert c.status == "FAIL" and "running" in c.detail
    # a tag the release does not name, and the kubelet's long form of a repository
    retag = text.replace("image: hapiproject/hapi@", "image: hapiproject/hapi:v7@", 1)
    inp3 = _inputs(pf.state_from_manifests(retag), TB_ENV="PRODUCTION")
    inp3.release = released
    assert pf.check_image_digests(inp3).status == "FAIL"
    assert released.by_repository("docker.io/hapiproject/hapi") is released.images["hapi"]
    # an image outside the release
    other = text.replace(f"image: trialbox-py@{DIGEST}", f"image: evil/trialbox-py@{DIGEST}", 1)
    inp2 = _inputs(pf.state_from_manifests(other), TB_ENV="PRODUCTION")
    inp2.release = released
    assert pf.check_image_digests(inp2).status == "FAIL"


def test_no_gpu_skips_the_gpu_checks_and_serving_record_is_honest(tmp_path: Path) -> None:
    st = _cluster(quota=ENOUGH)
    on = {c.name: c for c in pf.run(_inputs(st))}
    assert on["serving_record"].status == "FAIL" and "never assumed" in on["serving_record"].detail
    assert on["canary"].status == "FAIL"
    off = {c.name: c for c in pf.run(_inputs(st, no_gpu=True))}
    for name in ("serving_record", "gpu_serving", "canary"):
        assert (off[name].status, off[name].detail) == ("SKIP", pf.NO_DEVICE)
    assert set(on) == set(off) == {f.__name__.removeprefix("check_") for f in pf.PLATFORM_CHECKS}
    # a record for another MIG profile is not this partition's
    rec = json.loads((ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text(encoding="utf-8"))
    rec["card"]["mig_profile"] = "1g.23gb"
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    c = pf.check_serving_record(_inputs(st, TB_SERVING_RECORD=str(p), TB_MIG_PROFILE="3g.90gb"))
    assert c.status == "FAIL" and "MIG profile" in c.detail
    c = pf.check_serving_record(_inputs(st, TB_SERVING_RECORD=str(p), TB_MIG_PROFILE="1g.23gb"))
    assert c.status == "PASS"
    canary = tmp_path / "canary.json"
    canary.write_text(json.dumps({"ok": False, "at": "2026-11-10T01:00:00"}), encoding="utf-8")
    assert pf.check_canary(_inputs(st, TB_CANARY_RESULT=str(canary))).status == "FAIL"
    canary.write_text(json.dumps({"ok": True, "at": "2026-11-10T01:00:00"}), encoding="utf-8")
    assert pf.check_canary(_inputs(st, TB_CANARY_RESULT=str(canary))).status == "PASS"


def test_probes_and_evidenced_items() -> None:
    st = _cluster(quota=ENOUGH)

    def refuse(h: str, p: int) -> None:
        raise ConnectionRefusedError("refused")

    inp = _inputs(
        st, SMTP_HOST="smtp.hospa.test", TB_DIRECTORY_URL="ldaps://ad.hospa.test", TB_NTP_SERVER="ntp.hospa.test"
    )
    assert pf.check_mail_relay(inp).status == "PASS"
    assert pf.check_directory(inp).detail.endswith("ad.hospa.test:636 answers")
    assert pf.check_ntp(inp).status == "PASS"
    inp.connect = refuse
    assert pf.check_mail_relay(inp).status == "FAIL" and pf.check_directory(inp).status == "FAIL"
    inp.sntp = lambda s: 5.0
    assert pf.check_ntp(inp).status == "FAIL"
    assert pf.check_storage_encryption(_inputs(st)).status == "WARN"
    assert pf.check_storage_encryption(_inputs(st, TB_ENV="PRODUCTION")).status == "FAIL"
    ok = _inputs(st, TB_PLATFORM_STORAGE_ENCRYPTED="yes", TB_PLATFORM_STORAGE_EVIDENCE="CGMH-PLAT-SC-01")
    assert pf.check_storage_encryption(ok).status == "PASS"
    ok_cls = _inputs(
        st, TB_PLATFORM_STORAGE_ENCRYPTED="yes", TB_PLATFORM_STORAGE_EVIDENCE="x", TB_PLATFORM_STORAGE_CLASS="enc-rwx"
    )
    assert pf.check_storage_encryption(ok_cls).status == "FAIL"  # the base's claims name no class
    prod = _inputs(st, TB_ENV="PRODUCTION", TB_BACKUP_TARGETS="/mnt/backup")
    assert pf.check_backup_target(prod).status == "FAIL"
    prod2 = _inputs(st, TB_ENV="PRODUCTION", TB_BACKUP_TARGETS="/mnt/backup", TB_PLATFORM_BACKUP_EVIDENCE="NAS-7")
    assert pf.check_backup_target(prod2).status == "PASS"


def test_doctor_platform_cli_writes_evidence_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`trialbox doctor --platform --no-gpu` reports every check (the GPU ones skipped), writes iq-evidence.json and
    exits 1 when one fails, 0 when none does."""
    for k in list(os.environ):
        if k.startswith(("TB_", "SMTP_", "IMAP_")) or k in (
            "KUBERNETES_SERVICE_HOST",
            "NHI_TWPAS_BASE_URL",
            "CLOUD_LLM_BASE_URL",
            "EGRESS_EXTRA",
        ):
            monkeypatch.delenv(k, raising=False)
    objs = build("shared-quota")
    objs.append(
        {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "trialbox"}, "spec": {"hard": ENOUGH}}
    )
    man = tmp_path / "rendered.yaml"
    man.write_text(yaml.safe_dump_all(objs), encoding="utf-8")
    ev = tmp_path / "out" / "iq-evidence.json"
    # PRODUCTION (the manifests' TB_ENV): --no-gpu is refused before any check, and no evidence is written
    assert cli(["doctor", "--platform", "--no-gpu", "--manifests", str(man), "--evidence", str(ev)]) == 1
    assert "refused in VALIDATION and PRODUCTION" in capsys.readouterr().err and not ev.exists()
    rc = cli(["doctor", "--platform", "--manifests", str(man), "--evidence", str(ev)])
    doc = json.loads(ev.read_text(encoding="utf-8"))
    assert rc == 1 and doc["passed"] is False  # unreleased images, no serving record, nothing declared
    assert doc["no_gpu"] is False and by_status(doc, "SKIP") == set()
    monkeypatch.setenv("TB_ENV", "TEST")
    rc = cli(["doctor", "--platform", "--no-gpu", "--manifests", str(man), "--evidence", str(ev)])
    doc = json.loads(ev.read_text(encoding="utf-8"))
    assert rc == 0 and doc["passed"] is True, by_status(doc, "FAIL")  # TEST: what is not declared is a WARN
    assert doc["schema"] == pf.EVIDENCE_SCHEMA and doc["no_gpu"] is True and doc["gpu_profile"] == "shared-quota"
    by = {c["name"]: c for c in doc["checks"]}
    assert {n for n, c in by.items() if c["status"] == "SKIP"} == {"serving_record", "gpu_serving", "canary"}
    assert all(by[n]["detail"] == "skipped: no device" for n in ("serving_record", "gpu_serving", "canary"))
    assert {"topology", "routing_perimeter", "image_digests", "quota", "network_policy", "kek_custody", "ntp"} <= set(
        by
    )
    # a site whose declarations are all in place, with the egress policy its site overlay adds, passes (TEST, so
    # the unreleased tags are a warning)
    eg = doctor._egress()
    pols, _ = eg.render_networkpolicy(eg.allowlist({"SMTP_HOST": "smtp.hospa.test"}), lambda h: ["10.0.0.25"])
    man.write_text(yaml.safe_dump_all([*objs, *pols]), encoding="utf-8")
    good = {
        "TB_ENV": "TEST",
        "TB_NTP_SERVER": "ntp.hospa.test",
        "SMTP_HOST": "smtp.hospa.test",
        "TB_PLATFORM_STORAGE_ENCRYPTED": "yes",
        "TB_PLATFORM_STORAGE_EVIDENCE": "SC-1",
        "TB_BACKUP_TARGETS": "/mnt/nas",
        "TB_PLATFORM_BACKUP_EVIDENCE": "NAS-1",
    }
    for k, v in good.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(pf, "_connect", lambda h, p: None)
    monkeypatch.setattr(pf, "sntp_offset", lambda s, timeout=3.0: 0.002)
    monkeypatch.setattr(pf, "_resolve", lambda h: ["10.0.0.25"])  # the egress policy's ipBlocks, compared now
    rc = cli(["doctor", "--platform", "--no-gpu", "--manifests", str(man), "--evidence", str(ev)])
    doc = json.loads(ev.read_text(encoding="utf-8"))
    fails = [c for c in doc["checks"] if c["status"] == "FAIL"]
    assert rc == 0 and doc["passed"] is True, fails
    capsys.readouterr()
    # not in a cluster and nothing given: refused, not a pass
    assert cli(["doctor", "--platform"]) == 1


def by_status(doc: dict[str, Any], status: str) -> set[str]:
    return {c["name"] for c in doc["checks"] if c["status"] == status}


def test_compose_platform_form(tmp_path: Path) -> None:
    """The compose variant: the release's images, the GPU devices from the reservations, the platform's evidence
    reference for the network rule and the quota."""
    rel = pf.load_release()
    env = dict(line.split("=", 1) for line in pf.compose_env(rel))
    cfg = {
        "name": "trialbox",
        "services": {
            "lake": {"image": env["TB_IMAGE"]},
            "db": {"image": env["POSTGRES_IMAGE"]},
            "llm-service": {
                "image": env["VLLM_IMAGE"],
                "deploy": {
                    "resources": {
                        "reservations": {
                            "devices": [{"driver": "nvidia", "device_ids": ["MIG-a"], "capabilities": ["gpu"]}]
                        }
                    }
                },
            },
            "llm-verifier": {
                "image": env["VLLM_IMAGE"],
                "deploy": {
                    "resources": {
                        "reservations": {
                            "devices": [{"driver": "nvidia", "device_ids": ["MIG-b"], "capabilities": ["gpu"]}]
                        }
                    }
                },
            },
        },
    }
    st = pf.state_from_compose(cfg)
    assert pf.minimum(st)["gpu"] == 2
    assert pf.check_image_digests(_inputs(st)).status == "WARN"
    assert pf.check_quota(_inputs(st)).status == "FAIL"
    assert pf.check_quota(_inputs(st, TB_PLATFORM_QUOTA="gpu=1")).status == "FAIL"
    assert pf.check_quota(_inputs(st, TB_PLATFORM_QUOTA="gpu=2")).status == "PASS"
    assert pf.check_network_policy(_inputs(st)).status == "FAIL"
    assert pf.check_network_policy(_inputs(st, TB_PLATFORM_NETWORK_POLICY_EVIDENCE="FW-12")).status == "PASS"
    text = (ROOT / "deploy/platform/docker-compose.platform.yml").read_text(encoding="utf-8")
    doc = yaml.load(text, Loader=_Loader)
    for name, svc in doc["services"].items():
        assert svc["pull_policy"] == "never", name
        assert re.fullmatch(r"\$\{[A-Z_]+:\?[^}]+\}", svc["image"]), (name, svc["image"])
        var = svc["image"][2:].split(":", 1)[0]
        assert var in pf.COMPOSE_VARS, name
    assert doc["services"]["llm-verifier"]["profiles"] == ["gpu"]


def test_kube_api_never_keeps_a_secret_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sa = tmp_path / "sa"
    sa.mkdir()
    (sa / "token").write_text("t", encoding="utf-8")
    (sa / "namespace").write_text("trialbox", encoding="utf-8")
    monkeypatch.setattr("ssl.create_default_context", lambda cafile=None: None)
    api = pf.KubeApi(base="https://api.invalid", sa=sa)

    class _Resp:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    def fake(req: Any, context: Any = None, timeout: float = 0) -> _Resp:
        items: list[dict[str, Any]] = []
        if req.full_url.endswith("/secrets"):
            items = [{"metadata": {"name": "trialbox-db"}, "data": {"POSTGRES_PASSWORD": "c2VjcmV0"}}]
        assert req.headers["Authorization"] == "Bearer t"
        return _Resp(json.dumps({"items": items}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    st = api.state()
    assert st.source == "cluster" and st.namespace == "trialbox"
    assert st.of("Secret")[0]["data"] == {"POSTGRES_PASSWORD": ""}
    assert "c2VjcmV0" not in json.dumps(st.objects)


def test_doctor_status_skip_is_not_a_failure() -> None:
    checks = [doctor.Check("a", "PASS", ""), doctor.Check("b", "SKIP", pf.NO_DEVICE)]
    assert doctor.ok(checks) and "SKIP" in doctor.render(checks)


# ------------------------------------------------------------------------------------------------ review fixes
def _policy(name: str, spec: dict[str, Any], **labels: str) -> dict[str, Any]:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "labels": labels},
        "spec": spec,
    }


def test_network_policy_refuses_open_rules_and_drift() -> None:
    """Review fix 2: a false PASS. Policy names and annotations are not enough: an open rule anywhere (no ``to``,
    no ``from``, a /0 block), a changed model isolation, or egress ipBlocks other than the rendered ones fail."""
    st = _cluster(quota=ENOUGH)
    assert pf.open_rules(st.of("NetworkPolicy")) == []
    assert pf.check_network_policy(_inputs(st)).status == "PASS"
    open_doctor = _policy(
        "trialbox-doctor-egress",  # the rule the base shipped before: any address on these ports
        {
            "podSelector": {"matchLabels": {"app.kubernetes.io/component": "doctor"}},
            "policyTypes": ["Egress"],
            "egress": [{"ports": [{"protocol": "TCP", "port": 443}, {"protocol": "TCP", "port": 445}]}],
        },
    )
    world = _policy(
        "x-world",
        {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{"to": [{"ipBlock": {"cidr": "::/0"}}]}]},
    )
    any_in = _policy("x-in", {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{"from": []}]})
    v4 = _policy(
        "x-v4",
        {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}]}]},
    )
    for extra in (open_doctor, world, any_in, v4):
        bad = _cluster(quota=ENOUGH)
        bad.objects.append(extra)
        c = pf.check_network_policy(_inputs(bad))
        assert c.status == "FAIL" and "open rules" in c.detail and extra["metadata"]["name"] in c.detail, extra
    # model isolation must be the shipped one: an extra ingress source is a change
    iso = _cluster(quota=ENOUGH)
    pol = iso.named("NetworkPolicy", "trialbox-model-isolation")
    assert pol is not None
    pol["spec"]["ingress"][0]["from"].append({"podSelector": {"matchLabels": {"app.kubernetes.io/component": "lake"}}})
    c = pf.check_network_policy(_inputs(iso))
    assert c.status == "FAIL" and "trialbox-model-isolation differs" in c.detail
    # the API server's form of the shipped policy (no empty egress list, the default protocol) is the same policy
    same = _cluster(quota=ENOUGH)
    pol = same.named("NetworkPolicy", "trialbox-model-isolation")
    assert pol is not None
    del pol["spec"]["egress"]
    assert pf.check_network_policy(_inputs(same)).status == "PASS"
    # the annotation says smtp, the ipBlock is somewhere else
    eg = doctor._egress()
    env = {"SMTP_HOST": "smtp.hospa.test"}
    pols, _ = eg.render_networkpolicy(eg.allowlist({**env, "TB_ENV": "TEST"}), _dns)
    good = _cluster([*build("shared-quota"), *pols], quota=ENOUGH)
    assert pf.check_network_policy(_inputs(good, False, **env)).status == "PASS"
    moved = copy.deepcopy(pols)
    moved[0]["spec"]["egress"][0]["to"] = [{"ipBlock": {"cidr": "192.0.2.99/32"}}]
    c = pf.check_network_policy(_inputs(_cluster([*build("shared-quota"), *moved], quota=ENOUGH), False, **env))
    assert c.status == "FAIL" and "192.0.2.99/32" in c.detail


def test_doctor_egress_is_rendered_from_the_site_and_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review fix 3: the doctor reaches only the declared API server, NTP, directory, mail relay and backup hosts, as
    ipBlocks rendered like the egress allowlist; an undeclared host gets no rule; it lists Secrets and nothing more."""
    base = [o for o in build("shared-quota") if o["kind"] == "NetworkPolicy"]
    selects_doctor = [
        p
        for p in base
        if (p["spec"]["podSelector"].get("matchLabels") or {}).get("app.kubernetes.io/component") == "doctor"
    ]
    assert selects_doctor == [] and pf.open_rules(base) == []
    env = {
        "TB_PLATFORM_API_SERVER": "10.96.0.1:6443",
        "TB_NTP_SERVER": "ntp.hospa.test",
        "TB_DIRECTORY_URL": "ldaps://ad.hospa.test",
        "SMTP_HOST": "smtp.hospa.test",
        "SMTP_PORT": "25",
        "TB_PLATFORM_BACKUP_HOST": "nas.hospa.test:2049",
    }
    pol, warn = pf.render_doctor_policy(env, _dns)
    assert pol is not None and warn == []
    assert pol["spec"]["podSelector"] == {"matchLabels": {"app.kubernetes.io/component": "doctor"}}
    assert all(r["to"] for r in pol["spec"]["egress"]) and pf.open_rules([pol]) == []
    assert pf._blocks(pol) == {
        ("10.96.0.1/32", "TCP", "6443"),
        ("10.0.0.123/32", "UDP", "123"),
        ("10.0.0.40/32", "TCP", "636"),
        ("10.0.0.25/32", "TCP", "25"),
        ("2001:db8::25/128", "TCP", "25"),
        ("10.0.0.50/32", "TCP", "2049"),
    }
    # fail closed: nothing declared, nothing allowed; an unresolvable host gets no rule
    none, warn = pf.render_doctor_policy({}, _dns)
    assert none is None and len(warn) == 4 and all("not declared" in w for w in warn)
    part, warn = pf.render_doctor_policy({"TB_NTP_SERVER": "ntp.hospa.test", "SMTP_HOST": "nowhere.invalid"}, _dns)
    assert part is not None and pf._blocks(part) == {("10.0.0.123/32", "UDP", "123")}
    assert any("nowhere.invalid: does not resolve" in w for w in warn)
    # the command renders it with the allowlist
    envf = tmp_path / "site.env"
    envf.write_text("TB_PLATFORM_API_SERVER=10.96.0.1:6443\nTB_NTP_SERVER=10.0.0.123\n", encoding="utf-8")
    assert cli(["platform-egress", "--env-file", str(envf)]) == 0
    docs = {d["metadata"]["name"]: d for d in yaml.safe_load_all(capsys.readouterr().out) if d}
    assert pf._blocks(docs[pf.DOCTOR_POLICY]) == {("10.96.0.1/32", "TCP", "6443"), ("10.0.0.123/32", "UDP", "123")}
    # doctor --platform compares it with the declarations: a wider or another one fails
    eg = doctor._egress()
    allow_pols, _ = eg.render_networkpolicy(eg.allowlist({**env, "TB_ENV": "TEST"}), _dns)
    st = _cluster([*build("shared-quota"), *allow_pols, pol], quota=ENOUGH)
    assert pf.check_network_policy(_inputs(st, False, **env)).status == "PASS"
    wider = copy.deepcopy(pol)
    wider["spec"]["egress"][0]["to"].append({"ipBlock": {"cidr": "10.0.0.0/8"}})
    c = pf.check_network_policy(
        _inputs(_cluster([*build("shared-quota"), *allow_pols, wider], quota=ENOUGH), False, **env)
    )
    assert c.status == "FAIL" and "10.0.0.0/8" in c.detail
    st = _cluster([*build("shared-quota"), pol], quota=ENOUGH)
    c = pf.check_network_policy(_inputs(st))  # the site declares nothing, yet the doctor may reach hosts
    assert c.status == "FAIL" and "declares no doctor destination" in c.detail
    # the Role: Secrets are listed (kek_custody needs every name), never read one by one
    role = next(o for o in build("shared-quota") if o["kind"] == "Role" and o["metadata"]["name"] == "trialbox-doctor")
    secret_rules = [r for r in role["rules"] if "secrets" in r["resources"]]
    assert secret_rules == [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["list"]}]
    assert all(set(r["verbs"]) <= {"get", "list"} for r in role["rules"])


def test_no_gpu_is_refused_in_validation_and_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review fix 4: --no-gpu / TB_PLATFORM_NO_GPU can never turn the GPU checks into SKIP (and the evidence into
    ``passed: true``) in VALIDATION or PRODUCTION: the command refuses it, and the checks fail if given it anyway."""
    st = _cluster(quota=ENOUGH)
    for env in ("VALIDATION", "PRODUCTION"):
        by = {c.name: c for c in pf.run(_inputs(st, no_gpu=True, TB_ENV=env))}
        for name in ("serving_record", "gpu_serving", "canary"):
            assert by[name].status == "FAIL" and "refused" in by[name].detail, (env, name)
        q = pf.check_quota(_inputs(_cluster(quota={**ENOUGH, "requests.nvidia.com/gpu": "0"}), no_gpu=True, TB_ENV=env))
        assert q.status == "FAIL" and "gpu" in q.detail  # the GPU quota still counts
    man = tmp_path / "rendered.yaml"
    man.write_text(yaml.safe_dump_all(build("shared-quota")), encoding="utf-8")
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k, raising=False)
    import argparse

    for env in ("VALIDATION", "PRODUCTION"):
        for flag, extra in ((True, {}), (False, {"TB_PLATFORM_NO_GPU": "1"})):
            a = argparse.Namespace(manifests=man, compose_config=None, release=None, no_gpu=flag)
            with pytest.raises(pf.PlatformError, match="refused in VALIDATION and PRODUCTION"):
                pf.inputs_from(a, {"TB_ENV": env, **extra}, ROOT / "models" / "routing.yaml")
    a = argparse.Namespace(manifests=man, compose_config=None, release=None, no_gpu=True)
    assert pf.inputs_from(a, {"TB_ENV": "TEST"}, ROOT / "models" / "routing.yaml").no_gpu is True


def test_gpu_serving_enforces_one_judge_and_one_verifier_one_device_each() -> None:
    """Review fix 5: two devices, enforced: one judge and one verifier by ``trialbox.io/role``, one device each, no
    other GPU workload, a GPU quota of at least two."""

    def declared(objs: list[dict[str, Any]], quota: dict[str, str] | None = ENOUGH) -> pf.PlatformState:
        st = _cluster(objs, quota=quota)
        st.source = "manifests"  # what is declared; a cluster also needs the pods ready (below)
        return st

    assert pf.check_gpu_serving(_inputs(declared(build("shared-quota")))).status == "PASS"
    running = _cluster(quota=ENOUGH)
    c = pf.check_gpu_serving(_inputs(running))
    assert c.status == "FAIL" and "llm-service: no ready pod" in c.detail
    for comp in ("llm-service", "llm-verifier"):
        running.objects.append(
            {
                "kind": "Pod",
                "metadata": {"name": f"{comp}-0", "labels": {"app.kubernetes.io/component": comp}},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            }
        )
    assert pf.check_gpu_serving(_inputs(running)).status == "PASS"

    def variant(fn: Any, quota: dict[str, str] | None = ENOUGH) -> doctor.Check:
        objs = copy.deepcopy(build("shared-quota"))
        fn(objs)
        return pf.check_gpu_serving(_inputs(declared(objs, quota)))

    def dep(objs: list[dict[str, Any]], name: str) -> dict[str, Any]:
        return next(o for o in objs if o["kind"] == "Deployment" and o["metadata"]["name"] == name)

    def two_devices(objs: list[dict[str, Any]]) -> None:
        r = dep(objs, "llm-service")["spec"]["template"]["spec"]["containers"][0]["resources"]
        r["limits"]["nvidia.com/gpu"] = r["requests"]["nvidia.com/gpu"] = 2

    def no_verifier(objs: list[dict[str, Any]]) -> None:
        objs.remove(dep(objs, "llm-verifier"))

    def two_judges(objs: list[dict[str, Any]]) -> None:
        v = dep(objs, "llm-verifier")
        v["metadata"]["labels"]["trialbox.io/role"] = "judge"
        v["spec"]["template"]["metadata"]["labels"]["trialbox.io/role"] = "judge"

    def two_replicas(objs: list[dict[str, Any]]) -> None:
        dep(objs, "llm-verifier")["spec"]["replicas"] = 2

    def gpu_elsewhere(objs: list[dict[str, Any]]) -> None:
        c = dep(objs, "lake")["spec"]["template"]["spec"]["containers"][0]
        c["resources"].setdefault("limits", {})["nvidia.com/gpu"] = 1

    def unlabelled(objs: list[dict[str, Any]]) -> None:
        for name in ("llm-service", "llm-verifier"):
            d = dep(objs, name)
            d["metadata"]["labels"].pop("trialbox.io/role")
            d["spec"]["template"]["metadata"]["labels"].pop("trialbox.io/role")

    for fn, words in (
        (two_devices, "judge Deployment/llm-service takes 2"),
        (no_verifier, "0 verifier workloads"),
        (two_judges, "2 judge workloads"),
        (two_replicas, "verifier Deployment/llm-verifier takes 2"),
        (gpu_elsewhere, "Deployment/lake takes 1 GPU devices"),
        (unlabelled, "0 judge workloads"),
    ):
        c = variant(fn)
        assert c.status == "FAIL" and words in c.detail, (fn.__name__, c.detail)
    for quota in ({**ENOUGH, "requests.nvidia.com/gpu": "1"}, {"requests.cpu": "16"}, None):
        c = variant(lambda objs: None, quota)
        assert c.status == "FAIL" and "GPU quota" in c.detail, quota
    # the compose form names the pair by service
    gpu = {"resources": {"reservations": {"devices": [{"device_ids": ["MIG-a"], "capabilities": ["gpu"]}]}}}
    gpu2 = {"resources": {"reservations": {"devices": [{"device_ids": ["MIG-b"], "capabilities": ["gpu"]}]}}}
    cst = pf.state_from_compose(
        {"services": {"llm-service": {"image": "x", "deploy": gpu}, "llm-verifier": {"image": "x", "deploy": gpu2}}}
    )
    assert pf.check_gpu_serving(_inputs(cst, TB_PLATFORM_QUOTA="gpu=2")).status == "PASS"
    assert pf.check_gpu_serving(_inputs(cst, TB_PLATFORM_QUOTA="gpu=1")).status == "FAIL"


def test_quota_compares_requests_and_limits_apart() -> None:
    """Review fix 6: requests.* against the requests, limits.* against the limits (one figure for both let a large
    limits figure hide a small requests one), the lowest of several quotas, and a bounded limit every container sets."""
    need, lim = pf.minimum(_cluster()), pf.minimum(_cluster(), "limits")
    assert lim["memory"] > need["memory"]
    small_req = {**ENOUGH, "requests.memory": "8Gi", "limits.memory": "2Ti"}
    c = pf.check_quota(_inputs(_cluster(quota=small_req)))
    assert c.status == "FAIL" and "memory: quota 8.0Gi < profile minimum" in c.detail
    small_lim = {**ENOUGH, "limits.memory": f"{int(need['memory'] / 2**30) + 1}Gi"}
    c = pf.check_quota(_inputs(_cluster(quota=small_lim)))
    assert c.status == "FAIL" and "limits.memory: quota" in c.detail
    big_lim = {**ENOUGH, "limits.memory": f"{int(lim['memory'] / 2**30) + 1}Gi"}
    assert pf.check_quota(_inputs(_cluster(quota=big_lim))).status == "PASS"
    # two quotas: both apply, so the lower figure counts
    st = _cluster(quota=ENOUGH)
    st.objects.append(
        {"kind": "ResourceQuota", "metadata": {"name": "platform"}, "spec": {"hard": {"requests.cpu": "1"}}}
    )
    c = pf.check_quota(_inputs(st))
    assert c.status == "FAIL" and "cpu: quota 1 < profile minimum" in c.detail
    # a bounded limit no container sets: every pod would be refused by the quota
    c = pf.check_quota(_inputs(_cluster(quota={**ENOUGH, "limits.cpu": "1000"})))
    assert c.status == "FAIL" and "limits.cpu is bounded but" in c.detail
    # a bare name bounds requests, as in Kubernetes
    c = pf.check_quota(_inputs(_cluster(quota={**ENOUGH, "cpu": "1"})))
    assert c.status == "FAIL" and "cpu: quota 1" in c.detail


def test_storage_class_is_required_in_validation_and_production() -> None:
    """Review fix 7: without TB_PLATFORM_STORAGE_CLASS no claim is checked, so VALIDATION and PRODUCTION require it."""
    st = _cluster(quota=ENOUGH)
    declared = {"TB_PLATFORM_STORAGE_ENCRYPTED": "yes", "TB_PLATFORM_STORAGE_EVIDENCE": "SC-1"}
    assert pf.check_storage_encryption(_inputs(st, False, **declared)).status == "PASS"  # TEST
    for env in ("VALIDATION", "PRODUCTION"):
        c = pf.check_storage_encryption(_inputs(st, False, TB_ENV=env, **declared))
        assert c.status == "FAIL" and "TB_PLATFORM_STORAGE_CLASS" in c.detail
    objs = copy.deepcopy(build("shared-quota"))
    for o in objs:
        if o["kind"] == "PersistentVolumeClaim":
            o["spec"]["storageClassName"] = "enc-rwx"
        for t in (o.get("spec") or {}).get("volumeClaimTemplates") or [] if o["kind"] == "StatefulSet" else []:
            t["spec"]["storageClassName"] = "enc-rwx"
    ok = _inputs(_cluster(objs), False, TB_ENV="PRODUCTION", TB_PLATFORM_STORAGE_CLASS="enc-rwx", **declared)
    assert pf.check_storage_encryption(ok).status == "PASS"
