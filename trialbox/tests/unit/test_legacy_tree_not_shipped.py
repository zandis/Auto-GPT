"""The repository's top-level legacy code (everything outside ``trialbox/`` and ``.github/``) is never part of the
release build or its SBOM inputs (hygiene item 3). Read-only: the build commands, contexts and Dockerfiles of every
shipped image, the SBOM inputs and the host tree the bundle carries are read from the tree; no image is built.

Every recognised build line yields one verified, resolved context; an unresolved one fails. Named contexts, ``--from``
sources, the release closure and the ``SC_IMAGES`` assignments are all read. Every parser takes text, so each
regression case below feeds a planted string. A Docker context cannot reach above itself, so a build whose context
and named contexts resolve inside ``trialbox/`` cannot take a file of the legacy tree. Not covered: an environment
override of a ``?=`` variable at release time. The legacy tree is not deleted: its history stays."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.nodb, pytest.mark.guard]

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
MAKEFILE = ROOT / "Makefile"
KEEP_TOP = {"trialbox", ".github"}
# make release-images builds the shipped images; the targets in its closure with a build recipe are these two
RELEASE_START = "release-images"
RELEASE_BUILDERS = {"images", "demo-bundle"}
# the one script a release target calls that builds an image itself
DB_SCRIPT = "deploy/build_db_image.sh"
# built by hand for a registry (both architectures), not by release-images: its builds are read the same way
EXTRA_TARGETS = ("images-multiarch",)
# the only make variables a build line may carry as a bare word: each must expand to flags and their values only
FLAG_VARS = ("PLATFORM_ARG", "BUILD_ARGS", "CA_SECRET", "OCI_LABELS", "NO_CACHE_ARG")
BOOL_FLAGS = {"--push", "--load", "-q", "--quiet", "--no-cache", "--pull", "--rm"}
SC_IMAGES_TEXT = "$(SC_OWN_IMAGES) $(foreach i,$(SC_PLATFORM_IMAGES),registry:$(i)=$(SC_PLATFORM))"
# a shell separator, or a word: make references $(...) (one nesting level), quoted strings and plain characters
TOKEN = re.compile(r"""&&|\|\||[;|]|(?:\$\((?:[^()]|\([^()]*\))*\)|"[^"]*"|'[^']*'|[^\s;|&"'])+""")
SEPARATORS = {"&&", "||", ";", "|"}
BUILD_WORD = re.compile(r"\bdocker\s+(?:buildx\s+)?build\b")


class BuildError(ValueError):
    """A build line this guard cannot verify: it fails rather than pass unread."""


@dataclass
class Build:
    context: Path
    named: dict[str, str | Path] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------- readers of text


def _makefile_text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _joined(text: str) -> list[str]:
    """The lines of a make or shell text, continuation lines joined."""
    return text.replace("\\\n", " ").splitlines()


def _legacy_top(paths: list[str]) -> set[str]:
    """The top-level names of these tracked paths outside ``trialbox/`` and ``.github/``."""
    return {p.split("/", 1)[0] for p in paths if p} - KEEP_TOP


def _tracked() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return out.decode("utf-8", "surrogateescape").split("\0")


def _assignments(name: str, text: str) -> list[tuple[str, str]]:
    """Every assignment of a make variable in ``text``: (operator, value)."""
    found = []
    for line in _joined(text):
        m = re.match(rf"^(?:override\s+|export\s+)?{re.escape(name)}\s*(\?=|:=|::=|\+=|!=|=)\s*(.*)$", line)
        if m:
            found.append((m.group(1), m.group(2).strip()))
    return found


def _rules(text: str) -> dict[str, tuple[list[str], list[str]]]:
    """Each explicit rule's head: (prerequisites, recipe lines), continuation lines joined."""
    lines = _joined(text)
    rules: dict[str, tuple[list[str], list[str]]] = {}
    for i, line in enumerate(lines):
        if line.startswith(("\t", "#", ".")) or not line.strip():
            continue
        m = re.match(r"^([^\s:=#][^:=]*?)\s*:(?![:=])(.*)$", line)
        if not m or "=" in m.group(2).split("#", 1)[0]:
            continue  # not a rule, or a target-specific variable
        prereqs = [t for t in TOKEN.findall(m.group(2).split("#", 1)[0]) if t != "|"]
        recipe = []
        for body in lines[i + 1 :]:
            if not body.startswith("\t"):
                break
            recipe.append(body.strip())
        for head in m.group(1).split():
            rules[head] = (prereqs, recipe)
    return rules


def _recipe(target: str, text: str | None = None) -> list[str]:
    rules = _rules(_makefile_text() if text is None else text)
    assert target in rules, f"the Makefile has no rule {target}"
    return rules[target][1]


def _prereqs(target: str, text: str | None = None) -> list[str]:
    return _rules(_makefile_text() if text is None else text)[target][0]


def _segments(line: str) -> list[list[str]]:
    """The commands of one shell line, split at its separators; make's line prefixes and leading assignments off."""
    out: list[list[str]] = [[]]
    for tok in TOKEN.findall(line):
        if tok.startswith("#"):
            break  # a shell comment: the rest of the line is not run
        if tok in SEPARATORS:
            out.append([])
        else:
            out[-1].append(tok)
    cleaned = []
    for seg in out:
        if seg:
            seg[0] = seg[0].lstrip("@-+")
            seg = [t for t in seg if t]
        while seg and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[0]):
            seg = seg[1:]
        if seg and seg[0] == "exec":
            seg = seg[1:]
        if seg:
            cleaned.append(seg)
    return cleaned


def _make_goals(line: str) -> list[str]:
    """The goals of each ``$(MAKE)`` call in a recipe line."""
    goals = []
    for seg in _segments(line):
        if seg[0] != "$(MAKE)":
            continue
        goals += [t for t in seg[1:] if not t.startswith("-") and "=" not in t]
    return goals


def _closure(start: str, text: str) -> set[str]:
    """The targets ``make start`` can run: prerequisites and ``$(MAKE)`` goals, followed through the rules."""
    rules = _rules(text)
    seen: set[str] = set()
    todo = [start]
    while todo:
        target = todo.pop()
        if target in seen or target not in rules:
            continue
        seen.add(target)
        prereqs, recipe = rules[target]
        todo += prereqs
        for line in recipe:
            todo += _make_goals(line)
    return seen


def _literal(word: str) -> bool:
    return bool(word) and not any(c in word for c in "$`\"'*?") and not word.startswith("-")


def _resolve(cwd: Path, word: str) -> Path:
    return Path(os.path.normpath(cwd / word))


def _inside_trialbox(path: Path) -> bool:
    return Path(os.path.normpath(path)).is_relative_to(ROOT)


def _builds(line: str, cwd: Path = ROOT) -> list[Build]:
    """Each ``docker build`` / ``docker buildx build`` of one shell line, its context resolved from the folder the
    line runs in (each ``cd`` moves it). Raises BuildError on what cannot be verified: a ``cd`` to a non-literal, a
    context that is not one literal positional (``-``, a URL, a make variable), or a bare word that is not a flag
    variable of FLAG_VARS."""
    builds = []
    for seg in _segments(line):
        if seg[0] == "cd":
            if len(seg) != 2 or not _literal(seg[1]):
                raise BuildError(f"a cd to a non-literal folder: {' '.join(seg)}")
            cwd = _resolve(cwd, seg[1])
            continue
        if "docker" not in seg:
            continue
        i = seg.index("docker")
        rest = seg[i + 1 :]
        if rest[:1] == ["build"]:
            args = rest[1:]
        elif rest[:2] == ["buildx", "build"]:
            args = rest[2:]
        else:
            continue
        build = Build(context=cwd)
        positional: list[str] = []
        it = iter(args)
        for tok in it:
            if tok.startswith("$("):
                if tok[2:-1] not in FLAG_VARS:
                    raise BuildError(f"{tok}: a make variable as a bare word of a build (not one of FLAG_VARS)")
                continue
            if tok.startswith("-") and tok != "-":
                flag, eq, value = tok.partition("=")
                if flag in BOOL_FLAGS:
                    continue
                if not eq:
                    nxt = next(it, None)
                    if nxt is None:
                        raise BuildError(f"{flag} has no value")
                    value = nxt
                if flag == "--build-context":
                    name, _, where = value.partition("=")
                    if "://" in where:
                        build.named[name] = where
                    elif not _literal(where):
                        raise BuildError(f"--build-context {name}: a non-literal value {where}")
                    else:
                        build.named[name] = _resolve(cwd, where)
                elif flag in ("-t", "--tag"):
                    build.tags.append(value)
                continue
            positional.append(tok)
        if len(positional) != 1:
            raise BuildError(f"a build needs exactly one context, found {positional}")
        context = positional[-1]
        if context == "-" or "://" in context or not _literal(context):
            raise BuildError(f"a context that cannot be verified: {context}")
        build.context = _resolve(cwd, context)
        builds.append(build)
    if len(builds) != len(BUILD_WORD.findall(line)):
        raise BuildError(f"recognised {len(BUILD_WORD.findall(line))} builds, verified {len(builds)}: {line}")
    return builds


def _build_problems(target: str, text: str) -> list[str]:
    problems = []
    for line in _recipe(target, text):
        try:
            builds = _builds(line)
        except BuildError as exc:
            problems.append(f"make {target}: {exc}")
            continue
        for b in builds:
            if not _inside_trialbox(b.context):
                problems.append(f"make {target}: build context {b.context} is outside trialbox/")
            for name, where in b.named.items():
                if isinstance(where, Path) and not _inside_trialbox(where):
                    problems.append(f"make {target}: named context {name}={where} is outside trialbox/")
    return problems


def _flag_var_problems(text: str) -> list[str]:
    """Each flag variable has one assignment, expanding to flags and their values only, and no --build-context."""
    problems = []
    for name in FLAG_VARS:
        found = _assignments(name, text)
        if len(found) != 1:
            problems.append(f"{name} has {len(found)} assignments")
            continue
        value = found[0][1]
        m = re.fullmatch(r"\$\(if \$\([A-Z_]+\),(.*),\)", value)
        body = m.group(1) if m else value
        toks = TOKEN.findall(body)
        expect_value = False
        for tok in toks:
            if expect_value:
                expect_value = False
                continue
            if tok.startswith("--build-context"):
                problems.append(f"{name} holds --build-context")
                expect_value = "=" not in tok
            elif tok.startswith("-"):
                expect_value = tok not in BOOL_FLAGS and "=" not in tok
            else:
                problems.append(f"{name} holds a bare word {tok}")
    return problems


def _release_builders(text: str) -> set[str]:
    rules = _rules(text)
    return {t for t in _closure(RELEASE_START, text) if any(BUILD_WORD.search(line) for line in rules[t][1])}


def _called_files(line: str) -> set[str]:
    """The files of trialbox/ a recipe line runs: a path that is a file, or ``-m tools.x`` as tools/x.py."""
    out = set()
    for seg in _segments(line):
        for j, tok in enumerate(seg):
            if tok == "-m" and j + 1 < len(seg):
                mod = seg[j + 1].replace(".", "/")
                for cand in (f"{mod}.py", f"{mod}/__main__.py"):
                    if (ROOT / cand).is_file():
                        out.add(cand)
            elif "/" in tok and _literal(tok) and (ROOT / tok).is_file():
                out.add(tok)
    return out


def _holds_build(rel: str) -> bool:
    lines = (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    return any(BUILD_WORD.search(line) for line in lines if not line.lstrip().startswith("#"))


def _from_problems(text: str, label: str) -> list[str]:
    """R1 of the review: every ``COPY``/``ADD`` source stays in the context, every ``--from`` is a stage of the file."""
    problems = []
    stages: list[str] = []
    for line in _joined(text):
        words = line.split()
        if not words:
            continue
        op = words[0].upper()
        if op == "FROM":
            m = re.search(r"\s+AS\s+(\S+)\s*$", line, re.IGNORECASE)
            stages.append(m.group(1).lower() if m else "")
            continue
        if op == "RUN":
            for w in words[1:]:
                if not w.startswith("--mount="):
                    if not w.startswith("--"):
                        break
                    continue
                opts = dict(o.partition("=")[::2] for o in w[len("--mount=") :].split(","))
                src = opts.get("from")
                if src is not None and not (src.lower() in stages or src.isdigit()):
                    problems.append(f"{label}: RUN --mount from={src} is not a stage of the file")
            continue
        if op not in ("COPY", "ADD"):
            continue
        flags = [w for w in words[1:] if w.startswith("--")]
        rest = " ".join(w for w in words[1:] if not w.startswith("--"))
        args = json.loads(rest) if rest.startswith("[") else rest.split()
        src_from = next((f.split("=", 1)[1] for f in flags if f.startswith("--from=")), None)
        if src_from is not None:
            if not (src_from.lower() in stages or src_from.isdigit()):
                problems.append(f"{label}: {op} --from={src_from} is not a stage of the file")
            continue
        for src in args[:-1]:
            if src.startswith("/") or os.path.normpath(src).startswith(".."):
                problems.append(f"{label}: {op} {src} leaves the context")
    return problems


def _copy_sources(text: str) -> list[str]:
    """The context sources of a Dockerfile's ``COPY``/``ADD`` lines (not those of ``--from``)."""
    out: list[str] = []
    for line in _joined(text):
        words = line.split()
        if not words or words[0].upper() not in ("COPY", "ADD") or any(w.startswith("--from=") for w in words):
            continue
        rest = " ".join(w for w in words[1:] if not w.startswith("--"))
        args = json.loads(rest) if rest.startswith("[") else rest.split()
        out += args[:-1]
    return out


def _compose_problems(text: str, folder: Path, label: str) -> tuple[list[str], int]:
    """Each compose build's context and additional contexts resolve inside trialbox/ (the additional ones are read
    against both the compose file's folder and the build's context: inside under either)."""
    # compose's own merge tags (!reset, !override) are dropped: only the build keys are read here
    doc = yaml.safe_load(re.sub(r"!(reset|override)\b", "", text)) or {}
    problems, seen = [], 0
    for name, svc in (doc.get("services") or {}).items():
        build = (svc or {}).get("build")
        if build is None:
            continue
        seen += 1
        context = build if isinstance(build, str) else build.get("context", ".")
        ctx = _resolve(folder, str(context))
        if not _inside_trialbox(ctx):
            problems.append(f"{label}: {name} builds from {context}, outside trialbox/")
        extra = {} if isinstance(build, str) else build.get("additional_contexts") or {}
        pairs = extra.items() if isinstance(extra, dict) else (str(e).partition("=")[::2] for e in extra)
        for key, where in pairs:
            where = str(where)
            if "://" in where:
                continue
            if not (_inside_trialbox(_resolve(folder, where)) and _inside_trialbox(_resolve(ctx, where))):
                problems.append(f"{label}: {name} additional context {key}={where} is outside trialbox/")
    return problems, seen


def _db_script_tag() -> str:
    text = (ROOT / DB_SCRIPT).read_text(encoding="utf-8")
    m = re.search(r"^build=\(-f deploy/docker/db\.Dockerfile -t (\S+)\)$", text, re.MULTILINE)
    assert m, f"{DB_SCRIPT}: its build line changed: this test must follow it"
    return m.group(1)


def _sc_problems(text: str) -> list[str]:
    """R5 of the review: SC_IMAGES and SC_OWN_IMAGES are assigned once each, with ?=, to what the release builds."""
    problems = []
    for name in ("SC_IMAGES", "SC_OWN_IMAGES"):
        found = _assignments(name, text)
        if len(found) != 1 or found[0][0] != "?=":
            problems.append(f"{name}: {len(found)} assignments {[op for op, _ in found]}, not one ?=")
    if problems:
        return problems
    if _assignments("SC_IMAGES", text)[0][1] != SC_IMAGES_TEXT:
        problems.append("SC_IMAGES no longer reads " + SC_IMAGES_TEXT)
    tags = {_db_script_tag()}
    for target in sorted(RELEASE_BUILDERS):
        for line in _recipe(target, text):
            try:
                tags |= {t for b in _builds(line) for t in b.tags}
            except BuildError as exc:
                problems.append(f"make {target}: its tags cannot be read: {exc}")
    if problems:
        return problems
    own = set(_assignments("SC_OWN_IMAGES", text)[0][1].split())
    if own != tags:
        problems.append(f"SC_OWN_IMAGES {sorted(own)} is not the release builds' tags {sorted(tags)}")
    return problems


# ------------------------------------------------------------------------------------------------- the tree's guard


def test_the_legacy_tree_is_there() -> None:
    assert _legacy_top(_tracked()), "the repository has no top-level legacy tree any more: drop this test with a ruling"


def test_the_release_closure_builds_in_images_and_demo_bundle_only() -> None:
    text = _makefile_text()
    assert _release_builders(text) == RELEASE_BUILDERS
    rules = _rules(text)
    called = {f for t in _closure(RELEASE_START, text) for line in rules[t][1] for f in _called_files(line)}
    assert {f for f in called if _holds_build(f)} == {DB_SCRIPT}


@pytest.mark.parametrize("target", sorted(RELEASE_BUILDERS) + list(EXTRA_TARGETS))
def test_every_release_build_resolves_inside_trialbox(target: str) -> None:
    text = _makefile_text()
    assert any(BUILD_WORD.search(line) for line in _recipe(target, text)), f"make {target} builds no image any more"
    assert _build_problems(target, text) == []


def test_the_flag_variables_hold_flags_only() -> None:
    assert _flag_var_problems(_makefile_text()) == []


def test_the_database_image_script_builds_inside_trialbox() -> None:
    lines = (ROOT / DB_SCRIPT).read_text(encoding="utf-8").splitlines()
    assert 'cd "$(dirname "$0")/.."' in lines  # the script's folder's parent: trialbox/
    build = next(line for line in lines if line.startswith("exec docker build"))
    assert build.split()[-1] == "deploy/docker"
    assert "--build-context" not in "\n".join(lines)


def test_every_compose_build_context_is_inside_trialbox() -> None:
    seen = 0
    for compose in sorted((ROOT / "deploy").glob("docker-compose*.yml")):
        problems, n = _compose_problems(compose.read_text(encoding="utf-8"), compose.parent, compose.name)
        assert problems == []
        seen += n
    assert seen, "no compose file builds an image any more: this test must follow them"


def test_no_shipped_dockerfile_reads_outside_its_context_or_its_stages() -> None:
    (op, value), *more = _assignments("RELEASE_DOCKERFILES", _makefile_text())
    assert not more and op == ":="
    dockerfiles = value.split()
    assert len(dockerfiles) >= 6
    for rel in dockerfiles:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert _copy_sources(text), f"{rel} copies nothing from its context?"
        assert _from_problems(text, rel) == []


def test_the_scanned_images_are_the_release_images_and_their_dockerfiles() -> None:
    text = _makefile_text()
    assert _sc_problems(text) == []
    own = set(_assignments("SC_OWN_IMAGES", text)[0][1].split())
    ((_, scan),) = _assignments("IMAGE_SCAN_IMAGES", text)
    pairs = dict(item.split("=", 1) for item in scan.split())
    assert set(pairs) == own
    assert set(pairs.values()) == set(_assignments("RELEASE_DOCKERFILES", text)[0][1].split())


def test_the_sbom_inputs_are_inside_trialbox() -> None:
    # the lock's SBOM: an environment installed from trialbox's own lock, never the legacy requirements
    env = " ".join(_recipe("lock-env"))
    assert "-r deploy/requirements.lock" in env
    assert not re.search(r"(^|\s)(\.\./|/)\S*requirements", env)
    lock_sbom = " ".join(_recipe("lock-sbom"))
    assert "--env .cache/lock-env" in lock_sbom and "--out dist/sbom/" in lock_sbom
    # the release gates' SBOMs: one per image of SC_IMAGES (the images above) and the lock's SBOM
    gates = " ".join(_recipe("release-gates"))
    assert "--lock-sbom dist/sbom/requirements.lock.cdx.json" in gates
    assert "$(foreach i,$(SC_IMAGES),--image $(i))" in gates
    assert "dir:" not in gates
    # the licence report reads those SBOMs and nothing else
    assert _recipe("licences") == ["$(SC) licences dist/sbom/*.cdx.json --out dist/sbom/licences.md"]


def test_the_bundles_host_tree_is_packed_from_trialbox() -> None:
    text = (ROOT / "tools" / "make_bundle.sh").read_text(encoding="utf-8")
    assert 'ROOT="$(cd "$(dirname "$0")/.." && pwd)"' in text  # tools/..: trialbox/
    assert re.search(r'-m tools\.host_tree pack --root "\$ROOT"', text)


# ---------------------------------------------------------------------------------- the review's planted cases


def _planted_makefile(old: str, new: str) -> str:
    text = _makefile_text()
    assert text.count(old) == 1, old
    return text.replace(old, new)


GOOD_BUILD = "\tdocker build $(PLATFORM_ARG) $(OCI_LABELS) $(NO_CACHE_ARG) -f deploy/docker/jvm.Dockerfile -t trialbox-jvm:1.0.0 .\n"


def test_r1_a_copy_from_a_name_that_is_no_stage_fails() -> None:
    text = "FROM python:3.12 AS base\nCOPY --from=legacy /src /app\nCOPY --from=base /x /y\nCOPY --from=0 /x /y\n"
    assert _from_problems(text, "planted") == ["planted: COPY --from=legacy is not a stage of the file"]
    mount = "FROM python:3.12\nRUN --mount=type=bind,from=legacy,source=/x,target=/y true\n"
    assert _from_problems(mount, "planted") == ["planted: RUN --mount from=legacy is not a stage of the file"]


def test_r1_a_named_build_context_outside_trialbox_fails() -> None:
    text = _planted_makefile(GOOD_BUILD, GOOD_BUILD.replace("-f deploy/", "--build-context legacy=.. -f deploy/"))
    found = _build_problems("images", text)
    assert len(found) == 1 and f"named context legacy={REPO} is outside trialbox/" in found[0]
    url = _planted_makefile(
        GOOD_BUILD, GOOD_BUILD.replace("-f deploy/", "--build-context b=docker-image://x -f deploy/")
    )
    assert _build_problems("images", url) == []


@pytest.mark.parametrize("form", ["list", "mapping"])
def test_r1_a_compose_additional_context_outside_trialbox_fails(form: str) -> None:
    extra = "      additional_contexts:\n        - legacy=../..\n" if form == "list" else (
        "      additional_contexts:\n        legacy: ../..\n")  # fmt: skip
    text = f"services:\n  app:\n    build:\n      context: ..\n{extra}"
    problems, seen = _compose_problems(text, ROOT / "deploy", "planted.yml")
    assert seen == 1 and problems == ["planted.yml: app additional context legacy=../.. is outside trialbox/"]


def test_r2_a_cd_before_the_build_moves_its_context() -> None:
    (build,) = _builds("cd .. && docker build -f x -t y .")
    assert build.context == REPO and not _inside_trialbox(build.context)
    text = _planted_makefile(GOOD_BUILD, GOOD_BUILD + "\tcd .. && docker build -f x -t y .\n")
    assert _build_problems("images", text) == [f"make images: build context {REPO} is outside trialbox/"]


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ('cd "$$DIR" && docker build .', "a cd to a non-literal folder"),
        ("printf 'FROM x' | docker build -t y -", "a context that cannot be verified: -"),
        ("docker build -t y https://example.invalid/repo.git", "a context that cannot be verified: https://"),
    ],
)
def test_r2_a_context_that_cannot_be_resolved_fails(line: str, said: str) -> None:
    with pytest.raises(BuildError, match=re.escape(said)):
        _builds(line)


def test_r3_a_make_variable_as_the_context_fails_beside_a_good_build() -> None:
    text = _planted_makefile(GOOD_BUILD, GOOD_BUILD + "\tdocker build -f Dockerfile $(IMAGE_CONTEXT)\n")
    found = _build_problems("images", text)
    assert found == ["make images: $(IMAGE_CONTEXT): a make variable as a bare word of a build (not one of FLAG_VARS)"]


def test_r3_a_flag_variable_that_grows_a_bare_word_or_a_named_context_fails() -> None:
    text = _makefile_text().replace("NO_CACHE_ARG = $(if $(RELEASE_NO_CACHE),--no-cache,)",
                                    "NO_CACHE_ARG = --build-context legacy=.. ..", 1)  # fmt: skip
    assert _flag_var_problems(text) == ["NO_CACHE_ARG holds --build-context", "NO_CACHE_ARG holds a bare word .."]


def test_r4_a_new_prerequisite_of_release_images_that_builds_fails() -> None:
    text = _planted_makefile("release-images:\n", "release-images: extra-image\n")
    text += "\nextra-image:\n\tdocker build -f deploy/docker/python.Dockerfile -t extra:1 ..\n"
    assert _release_builders(text) == RELEASE_BUILDERS | {"extra-image"}
    via_make = _planted_makefile("\t$(MAKE) images demo-bundle", "\t$(MAKE) images demo-bundle extra-image")
    via_make += "\nextra-image:\n\tdocker build -t extra:1 ..\n"
    assert "extra-image" in _release_builders(via_make)


def test_r5_a_second_assignment_of_sc_images_fails_on_the_count() -> None:
    text = _makefile_text() + "\nSC_IMAGES += dir:../legacy\n"
    assert _sc_problems(text) == ["SC_IMAGES: 2 assignments ['?=', '+='], not one ?="]


def test_r6_a_top_level_name_that_starts_with_trialbox_is_legacy_too() -> None:
    assert _legacy_top(["trialbox-notes.md", "trialbox/x"]) == {"trialbox-notes.md"}
