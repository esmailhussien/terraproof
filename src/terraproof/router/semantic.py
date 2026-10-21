"""Optional CPU-only semantic section retrieval (never imported by lexical routing).

Install: python -m pip install -e ".[semantic]"
Download explicitly: python -m terraproof.router --download-model
Routing itself is local-only, including when TERRAPROOF_SEMANTIC=1. No task text
leaves the process. A missing extra/model, corrupt cache or inference failure is
reported by find_guidance as a lexical-fallback reason, not an exception.

FastEmbed 0.9.0 (Apache-2.0), supported mean-pooled multilingual MiniLM, 384 dims:
https://github.com/qdrant/fastembed/blob/v0.9.0/fastembed/text/pooled_embedding.py
Model/quantized ONNX source (Apache-2.0, 235,052,644-byte ONNX + ~17 MB tokenizer):
https://huggingface.co/Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q
The immutable source revision below is fetched explicitly through huggingface_hub;
FastEmbed gets a specific local path, never its unpinned default downloader.

Section windows retain real registry explanations, titles and section text. Each
section uses its best window cosine; round to six decimals BEFORE fusion/ties.
Fusion/selection settings live in __init__.py. Same model/runtime/input is stable;
results can change with model, tokenizer, ONNX runtime or preprocessing versions.

User cache: %LOCALAPPDATA%/terraproof/router on Windows, ~/Library/Caches on macOS,
$XDG_CACHE_HOME/terraproof/router (or ~/.cache/terraproof/router) elsewhere.
TERRAPROOF_CACHE_DIR overrides the terraproof cache root. Models and content-keyed
section arrays stay outside the repository by default; no queries are persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from .index import PROCESS_SKILLS, Index

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_SOURCE = "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
MODEL_REVISION = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
MODEL_FILES = ("config.json", "model_optimized.onnx", "special_tokens_map.json",
               "tokenizer.json", "tokenizer_config.json")
CACHE_VERSION = 1
PRECISION = 6
_MEMORY: dict[tuple[str, str], object] = {}


def cache_dir() -> Path:
    override = os.environ.get("TERRAPROOF_CACHE_DIR")
    if override:
        return Path(override).expanduser() / "router"
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "terraproof" / "router"


def model_path(*, download: bool = False) -> Path:
    """Only the explicit download command may access Hugging Face."""
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(repo_id=MODEL_SOURCE, revision=MODEL_REVISION,
                                  cache_dir=str(cache_dir() / "models"),
                                  allow_patterns=list(MODEL_FILES),
                                  local_files_only=not download))


@lru_cache(maxsize=1)
def get_embedder():
    # Deliberately lazy: neither fastembed nor numpy is needed by the base router.
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_NAME, specific_model_path=str(model_path()),
                         providers=["CPUExecutionProvider"], threads=1,
                         local_files_only=True)


def content_key(index: Index) -> str:
    """Hash all registry metadata AND actual section contents, plus model/schema."""
    payload = {"version": CACHE_VERSION, "model": MODEL_NAME, "revision": MODEL_REVISION,
               "skills": index.skills,
               "sections": [(s.skill, s.id, s.title, s.source, s.text) for s in index.sections]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _documents(index: Index) -> tuple[list[str], list[tuple[str, str]]]:
    documents, owners = [], []
    for section in index.sections:
        if section.skill in PROCESS_SKILLS:
            continue
        metadata = index.skills[section.skill]
        prefix = f"{section.skill}: {metadata['explanation']} {section.title}. "
        words = re.sub(r"[`#*|]", " ", section.text).split()
        # Small overlapping windows avoid losing the end of long sections to the
        # model's 128-token truncation. No hand-written symptom/skill mappings.
        for start in range(0, max(1, len(words)), 48):
            documents.append(prefix + " ".join(words[start:start + 64]))
            owners.append((section.skill, section.id))
    return documents, owners


def _unit_rows(values, expected: int):
    import numpy as np
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != expected or not matrix.shape[1] or not np.isfinite(matrix).all():
        raise ValueError("invalid semantic embedding shape or non-finite values")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms == 0).any():
        raise ValueError("zero semantic embedding")
    return matrix / norms


def section_scores(index: Index, task: str) -> dict[tuple[str, str], float]:
    """Cache document embeddings once per content key; embed queries in memory only."""
    import numpy as np
    embedder = get_embedder()
    documents, owners = _documents(index)
    key = content_key(index)
    directory = cache_dir() / "sections"
    path = directory / f"{key}.npy"
    memory_key = (str(directory.resolve()), key)
    matrix = _MEMORY.get(memory_key)
    if matrix is None:
        try:
            matrix = _unit_rows(np.load(path, allow_pickle=False), len(documents))
        except (OSError, ValueError, EOFError):
            matrix = _unit_rows(list(embedder.embed(documents, batch_size=32)), len(documents))
            directory.mkdir(parents=True, exist_ok=True)
            # Atomic replacement: concurrent readers never observe a partial array.
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".npy", delete=False) as handle:
                temporary = Path(handle.name)
                try:
                    np.save(handle, matrix, allow_pickle=False)
                except BaseException:
                    handle.close()
                    temporary.unlink(missing_ok=True)
                    raise
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        # Bound memory in long-running hosts that load different registries.
        _MEMORY.clear()
        _MEMORY[memory_key] = matrix
    query = _unit_rows(list(embedder.embed([task], batch_size=1)), 1)
    if query.shape[1] != matrix.shape[1]:
        raise ValueError("semantic query/document dimension mismatch")
    similarities = np.round(matrix @ query[0], PRECISION)
    scores: dict[tuple[str, str], float] = {}
    for owner, similarity in zip(owners, similarities):
        value = float(similarity)
        scores[owner] = max(scores.get(owner, -1.0), value)
    return scores
