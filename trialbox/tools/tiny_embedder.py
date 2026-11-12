"""A tiny embedder folder in the publisher's format, made on the spot with random weights (ENG-003, D-563).

    python -m tools.tiny_embedder --out /work/models/embedder       # inside the trialbox-embed image

For the PRODUCTION start test of the embed service: the test must load a real ``sentence-transformers`` folder
(safetensors weights, a tokenizer, the module list) through the same code a box runs, and no model may be
downloaded for it. The folder holds a one-layer transformer of 32 dimensions over a vocabulary of a few hundred
word pieces: about 100 kB, built in a second. Its vectors mean nothing; that it loads, is pinned and answers is the
point. Synthetic by construction: the vocabulary is letters, digits and a few clinical words.
"""

from __future__ import annotations

import argparse
import string
import tempfile
from pathlib import Path

DIM = 32
WORDS = ("patient", "history", "of", "the", "and", "no", "with", "gout", "diabetes", "fever", "pain", "blood", "test")


def vocabulary() -> list[str]:
    pieces = [*string.ascii_lowercase, *string.digits, *WORDS]
    return ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", *pieces, *(f"##{p}" for p in pieces)]


def build(out: Path) -> Path:
    """Write the folder; needs the ``embed`` extra (the trialbox-embed image has it)."""
    # in the embed image only, not in the box's venv; no blanket rule in pyproject: another tool's own ignore for
    # the same library would then be reported as unused
    import torch  # type: ignore[import-not-found,unused-ignore]
    from sentence_transformers import SentenceTransformer, models
    from transformers import (  # type: ignore[import-not-found,unused-ignore]
        BertConfig,
        BertModel,
        BertTokenizerFast,
    )

    torch.manual_seed(0)  # the same folder every time, so its manifest is stable within one build of the image
    with tempfile.TemporaryDirectory() as raw:
        vocab = Path(raw) / "vocab.txt"
        vocab.write_text("\n".join(vocabulary()) + "\n", encoding="utf-8")
        tokenizer = BertTokenizerFast(vocab_file=str(vocab), do_lower_case=True)
        config = BertConfig(vocab_size=len(vocabulary()), hidden_size=DIM, num_hidden_layers=1, num_attention_heads=2,
                            intermediate_size=64, max_position_embeddings=64)  # fmt: skip
        BertModel(config).save_pretrained(raw, safe_serialization=True)
        tokenizer.save_pretrained(raw)
        word = models.Transformer(raw, max_seq_length=64)
        st = SentenceTransformer(modules=[word, models.Pooling(DIM, pooling_mode="mean")], device="cpu")
        out.mkdir(parents=True, exist_ok=True)
        st.save(str(out), safe_serialization=True, create_model_card=False)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    path = build(a.out)
    print(f"tiny embedder: {path} ({sum(1 for p in path.rglob('*') if p.is_file())} files, {DIM} dimensions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
