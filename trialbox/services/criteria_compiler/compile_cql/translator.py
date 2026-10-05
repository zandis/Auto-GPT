"""cql-to-elm (cqframework 5.4.0, the version HAPI 8.12 CR runs) as a subprocess (SPEC §6.2).

Compilation fails on any translator error and on warnings of type ``semantic`` in TrialBox-generated libraries
(FHIRHelpers' own shadowing warnings are ignored: it is the upstream library).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FHIRHELPERS_ENTRY = "org/hl7/fhir/FHIRHelpers-4.0.1.cql"


class TranslationError(RuntimeError):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("CQL translation failed:\n" + "\n".join(messages[:30]))
        self.messages = messages


@dataclass
class Translation:
    elm: dict[str, str]  # library name -> ELM JSON text
    warnings: list[str] = field(default_factory=list)


def _lib_dir() -> Path:
    env = os.environ.get("TB_CQL_TRANSLATOR_LIB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / ".cache" / "jvm" / "cql-translator" / "lib"


def available() -> bool:
    lib = _lib_dir()
    return (
        lib.is_dir()
        and any(lib.glob("cql-to-elm-cli-*.jar"))
        and shutil.which(os.environ.get("TB_JAVA", "java")) is not None
    )


def fhirhelpers_source() -> str:
    for jar in sorted(_lib_dir().glob("quick-*.jar")):
        with zipfile.ZipFile(jar) as zf:
            return zf.read(FHIRHELPERS_ENTRY).decode("utf-8")
    raise FileNotFoundError("FHIRHelpers-4.0.1.cql not found in the cql-translator jars")


def _annotations(elm: dict[str, Any]) -> list[dict[str, Any]]:
    anns = elm.get("library", {}).get("annotation", []) or []
    return [a for a in anns if a.get("type") == "CqlToElmError"]


class Translator:
    def __init__(self, lib_dir: Path | None = None, java: str | None = None) -> None:
        self.lib_dir = lib_dir or _lib_dir()
        self.java = java or os.environ.get("TB_JAVA", "java")

    def translate(self, sources: dict[str, str], check: set[str] | None = None) -> Translation:
        """Translate ``{library_name: cql_text}`` (all includes must be present). ``check`` = libraries whose
        semantic warnings fail the compilation (default: all except FHIRHelpers)."""
        check = check if check is not None else {n for n in sources if n != "FHIRHelpers"}
        with tempfile.TemporaryDirectory(prefix="tbcql-") as td:
            src = Path(td) / "cql"
            out = Path(td) / "elm"
            src.mkdir()
            out.mkdir()
            files: dict[str, Path] = {}
            for name, text in sources.items():
                version = "4.0.1" if name == "FHIRHelpers" else _version(text)
                files[name] = src / f"{name}-{version}.cql"
                files[name].write_text(text, encoding="utf-8")
            elm: dict[str, str] = {}
            messages: list[str] = []
            warnings: list[str] = []
            for name, path in sorted(files.items()):
                target = out / f"{name}.json"
                cmd = [
                    self.java,
                    "-cp",
                    f"{self.lib_dir}/*",
                    "org.cqframework.cql.cql2elm.cli.Main",
                    "--input",
                    str(path),
                    "--format",
                    "JSON",
                    "--output",
                    str(target),
                    "--signatures",
                    "Overloads",
                    "--result-types",
                    "--annotations",
                    "--locators",
                    "--detailed-errors",
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
                if not target.exists():
                    messages.append(f"{name}: translator produced no output: {proc.stdout[-800:]} {proc.stderr[-800:]}")
                    continue
                text = target.read_text(encoding="utf-8")
                for ann in _annotations(json.loads(text)):
                    sev, typ = ann.get("errorSeverity"), ann.get("errorType")
                    msg = f"{name}:{ann.get('startLine')}:{ann.get('startChar')} [{sev}/{typ}] {ann.get('message')}"
                    if sev == "error" or (sev == "warning" and typ == "semantic" and name in check):
                        messages.append(msg)
                    elif sev == "warning":
                        warnings.append(msg)
                elm[name] = text
            if messages:
                raise TranslationError(messages)
            return Translation(elm, warnings)


def _version(cql: str) -> str:
    for line in cql.splitlines():
        line = line.strip()
        if line.startswith("library ") and " version " in line:
            return line.split(" version ", 1)[1].strip().strip("'")
    return "1.0.0"
