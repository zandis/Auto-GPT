"""Dense text embeddings (SPEC §4.7): the pinned local embedder (1024-d) in production, deterministic feature hashing
in CPU CI (D-12).

**Modes** (``TB_EMBED_MODE``, T-607, D-429, review LLM-013): ``model`` is the local embedder, weights from the offline
models volume (``TB_EMBED_MODEL_PATH``) loaded with sentence-transformers; ``hash`` the feature-hash stub; ``http``
the client of this service. ``bge-m3``, the mode name before D-429, is read as ``model`` so an older ``.env`` still
starts. :data:`MODES` is the list the settings wizard writes from.

**The service in PRODUCTION** (:func:`service_embedder`): ``hash`` is refused, so an unset mode never embeds a
production lake with the stub; ``model`` loads only weights that match the site's pin. The pin is the one
``tools/pin_model.py`` writes for :data:`EMBED_BUILD` into the site override (``TB_REGISTRY_OVERRIDE``): its
``sha256`` is the digest of the folder's weight manifest, computed here in the same format (:func:`manifest_sha256`).
In every environment a folder with pickle weights or Python files is refused, and one without safetensors weights
too (SEC-63, DEP-010: "safetensors from the publisher" is a criterion of D-429).
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

DIM = 1024
EMBED_BUILD = "e-embed-1"  # the embedder's build in models/registry.yaml (D-429)
DEFAULT_MODEL_PATH = "/models/embedder"
MODES = ("model", "hash", "http")
MODE_ALIASES = {"bge-m3": "model"}  # the mode name before D-429
REFUSED_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".py", ".pyc")  # as tools/pin_model.py
_CHUNK = 8 << 20


class EmbedderRefused(RuntimeError):
    """The embed service will not start with this configuration."""


class Embedder(Protocol):
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Signed feature hashing of CJK bigrams + Latin tokens into 1024 dims, L2-normalised. Deterministic."""

    model = "hash-1024-v1"
    dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        from lake.textproc import tokens

        out = []
        for text in texts:
            vec = [0.0] * DIM
            for tok in tokens(text):
                h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % DIM
                vec[idx] += 1.0 if h[4] & 1 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def _visible_files(folder: Path) -> list[Path]:
    return sorted(
        (
            p
            for p in folder.rglob("*")
            if p.is_file() and not any(s.startswith(".") for s in p.relative_to(folder).parts)
        ),
        key=lambda p: p.relative_to(folder).as_posix(),
    )


def check_folder(folder: Path) -> list[Path]:
    """The visible files of a weight folder; :class:`EmbedderRefused` when it is missing, holds pickle weights or
    code, or holds no safetensors weights."""
    if not folder.is_dir():
        raise EmbedderRefused(f"{folder}: no embedder weights (not a directory)")
    files = _visible_files(folder)
    refused = [p.relative_to(folder).as_posix() for p in files if p.suffix.lower() in REFUSED_SUFFIXES]
    if refused:
        raise EmbedderRefused(f"{folder}: refused file types (pickle or code, SEC-63): {', '.join(refused[:5])}")
    if not any(p.suffix.lower() == ".safetensors" for p in files):
        raise EmbedderRefused(f"{folder}: no .safetensors weights (D-429: safetensors from the publisher)")
    return files


def manifest_sha256(folder: Path) -> str:
    """The digest of the folder's weight manifest, in ``tools/pin_model.py``'s format (``<sha256>  <path>`` lines,
    sorted by path, hidden files left out)."""
    lines = []
    for p in check_folder(folder):
        h = hashlib.sha256()
        with p.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                h.update(chunk)
        lines.append(f"{h.hexdigest()}  {p.relative_to(folder).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def pinned_sha256(environ: Mapping[str, str]) -> str | None:
    """The site's pin of :data:`EMBED_BUILD` (``sha256`` in the override ``TB_REGISTRY_OVERRIDE``), or None."""
    path = (environ.get("TB_REGISTRY_OVERRIDE") or "").strip()
    if not path or not Path(path).is_file():
        return None
    import yaml

    doc: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entry = (doc.get("builds") or {}).get(EMBED_BUILD) or {}
    sha = entry.get("sha256") if isinstance(entry, dict) else None
    return str(sha) if sha else None


MAX_TOKENS = 512  # TB_EMBED_MAX_TOKENS: an input is cut here (a note sentence is far shorter; a pasted report is not)
BATCH_TOKENS = 8192  # TB_EMBED_BATCH_TOKENS: the tokens one encode call holds (its memory grows with them, not texts)


def _setting(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    return max(1, int(raw)) if raw else default


def token_batches(lengths: list[int], max_tokens: int, budget: int) -> list[list[int]]:
    """Indexes of the inputs in batches whose tokens (each input counted at most ``max_tokens``) stay within
    ``budget``; inputs of like length go together, so little of a batch is padding. Every input is in one batch."""
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    out: list[list[int]] = []
    cur: list[int] = []
    used = 0
    for i in order:
        n = min(lengths[i], max_tokens)
        width = max(n, max((min(lengths[j], max_tokens) for j in cur), default=0))
        if cur and width * (len(cur) + 1) > budget:  # padded to the longest: the batch's real size
            out.append(cur)
            cur, used = [], 0
        cur.append(i)
        used += n
    if cur:
        out.append(cur)
    return out


class LocalEmbedder:
    """The local embedder: dense vectors via sentence-transformers from the offline models volume. Never runs code
    from the folder (``trust_remote_code=False``) and never loads pickle weights (:func:`check_folder`)."""

    model = EMBED_BUILD
    dim = DIM

    def __init__(self, path: str, batch_size: int = 64, weights_sha256: str | None = None) -> None:
        check_folder(Path(path))
        from sentence_transformers import SentenceTransformer

        self._st = SentenceTransformer(path, device=os.environ.get("TB_EMBED_DEVICE", "cpu"), trust_remote_code=False)
        # the dimension is the loaded embedder's own (D-429: known only after G1; the vector store reads it, D-439)
        size = getattr(self._st, "get_sentence_embedding_dimension", lambda: None)()
        self.dim = int(size) if size else DIM
        self.batch_size = batch_size
        self.weights_sha256 = weights_sha256
        # red of 2026-11-15: no cap on input length and a fixed batch of 64 texts; a batch of long reports took 33 s
        # and the memory of a batch grows with its tokens. Inputs are cut at max_tokens, batches sized by tokens
        self.max_tokens = _setting("TB_EMBED_MAX_TOKENS", MAX_TOKENS)
        self.budget = max(self.max_tokens, _setting("TB_EMBED_BATCH_TOKENS", BATCH_TOKENS))
        self._st.max_seq_length = min(int(getattr(self._st, "max_seq_length", 0) or self.max_tokens), self.max_tokens)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        tok = getattr(self._st, "tokenizer", None)
        if tok is not None:
            lengths = [len(x) for x in tok(texts, truncation=True, max_length=self.max_tokens)["input_ids"]]
        else:  # no tokenizer to ask: characters, never fewer than its tokens for these models
            lengths = [len(t) for t in texts]
        out: list[list[float]] = [[] for _ in texts]
        for batch in token_batches(lengths, self.max_tokens, self.budget):
            vecs = self._st.encode([texts[i] for i in batch], batch_size=len(batch), normalize_embeddings=True,
                                   show_progress_bar=False)  # fmt: skip
            for i, v in zip(batch, vecs, strict=True):
                out[i] = [float(x) for x in v]
        return out


class HttpEmbedder:
    """Client for embed-service ``POST /embed``."""

    def __init__(self, base_url: str, model: str = "remote", timeout: float = 300) -> None:
        import httpx

        self.base_url = base_url.rstrip("/")
        from tb_common.service_auth import auth_headers

        self.client = httpx.Client(timeout=timeout, headers=auth_headers())  # D-127 (F-11)
        self.model = model
        self.dim = DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            resp = self.client.post(f"{self.base_url}/embed", json={"texts": texts[i : i + 64]})
            resp.raise_for_status()
            body = resp.json()
            self.model = body["model"]
            self.dim = int(body.get("dim") or self.dim)  # the service's embedder decides (D-439)
            out.extend(body["vectors"])
        return out


def normalise_mode(mode: str) -> str:
    m = (mode or "").strip().lower()
    m = MODE_ALIASES.get(m, m)
    if m not in MODES:
        raise ValueError(f"unknown TB_EMBED_MODE {mode!r}; use one of {', '.join(MODES)}")
    return m


def from_env(mode: str | None = None, url: str | None = None) -> Embedder:
    m = normalise_mode(mode or os.environ.get("TB_EMBED_MODE", "hash"))
    if m == "hash":
        return HashEmbedder()
    if m == "http":
        return HttpEmbedder(url or os.environ.get("EMBED_URL", "http://embed-service:8014"))
    return LocalEmbedder(os.environ.get("TB_EMBED_MODEL_PATH", DEFAULT_MODEL_PATH))


def service_embedder(environ: Mapping[str, str] | None = None) -> Embedder:
    """The embedder the embed service serves (T-607, LLM-013, LLM-014). In PRODUCTION (``TB_ENV``, PRODUCTION when
    unset) the stub is refused and the weights must match the site's pin of :data:`EMBED_BUILD`; elsewhere a pin, when
    there is one, is still checked. :class:`EmbedderRefused` names the fix."""
    from tb_common.config import environment_name

    env = os.environ if environ is None else environ
    production = environment_name(env) == "PRODUCTION"
    raw = env.get("TB_EMBED_MODE") or ("model" if production else "hash")
    try:
        mode = normalise_mode(raw)
    except ValueError:  # D-636: the service's own sentence, written here; never an error's text
        raise EmbedderRefused(f"unknown TB_EMBED_MODE {raw!r}; use one of {', '.join(MODES)}") from None
    if mode == "http":
        raise EmbedderRefused("TB_EMBED_MODE http is the client of this service, not a mode it serves")
    if mode == "hash":
        if production:
            raise EmbedderRefused(
                "TB_EMBED_MODE hash is the CI stub and is refused in PRODUCTION; set TB_EMBED_MODE=model and pin the "
                f"embedder (python -m tools.pin_model --build {EMBED_BUILD} --endpoint embed ...)"
            )
        return HashEmbedder()
    path = Path(env.get("TB_EMBED_MODEL_PATH") or DEFAULT_MODEL_PATH)
    want = pinned_sha256(env)
    if want is None and production:
        raise EmbedderRefused(
            f"no pin for {EMBED_BUILD} in the site override (TB_REGISTRY_OVERRIDE): the embedder's weights cannot be "
            f"checked; pin them with python -m tools.pin_model --build {EMBED_BUILD} --endpoint embed ..."
        )
    got = manifest_sha256(path)
    if want is not None and got != want:
        raise EmbedderRefused(
            f"{path}: these are not the pinned weights of {EMBED_BUILD}: manifest {got[:12]} differs from the pin "
            f"{want[:12]}; refused"
        )
    return LocalEmbedder(str(path), weights_sha256=got)
