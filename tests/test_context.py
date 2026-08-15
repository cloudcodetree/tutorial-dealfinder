"""Context-window token counting must find the bge-small tokenizer regardless of
which embed backend cached it (Part 16).

The `/context` endpoint 500'd in the containerized stack because `_tokenizer()`
only looked in the sentence-transformers HF-hub path (BAAI/bge-small-en-v1.5),
but embed.py uses fastembed, which caches the ONNX repo
(qdrant/bge-small-en-v1.5-onnx-q) under its own cache dir. These pin the path
resolver to both locations, offline (no real tokenizer load).
"""
import pytest

import dealfinder.context as ctx


def test_find_tokenizer_path_locates_a_fastembed_style_cache(tmp_path):
    root = tmp_path / "fastembed_cache" / "models--qdrant--bge-small-en-v1.5-onnx-q" / "snapshots" / "abc123"
    root.mkdir(parents=True)
    (root / "tokenizer.json").write_text("{}")
    found = ctx._find_tokenizer_path(roots=[str(tmp_path / "fastembed_cache")])
    assert found.endswith("tokenizer.json") and "bge-small" in found.lower()


def test_find_tokenizer_path_prefers_bge_small_and_ignores_others(tmp_path):
    other = tmp_path / "models--some--other-model" / "snapshots" / "x"
    other.mkdir(parents=True)
    (other / "tokenizer.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        ctx._find_tokenizer_path(roots=[str(tmp_path)])


def test_find_tokenizer_path_raises_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        ctx._find_tokenizer_path(roots=[str(tmp_path)])
