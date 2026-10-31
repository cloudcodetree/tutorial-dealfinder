"""Embedding model lifecycle — the lazy singleton must be thread-safe and warmable.

The `/semantic` + `/search` embed path loads a ~130MB fastembed model lazily on
first use. Two failure modes this pins down (Part 13 pgvector serving):
  1. concurrent first-callers must not each construct (download) the model — a
     race on `_get_model()` caused the pgvector path to wedge on fastembed's
     download file-locks under a cold, multi-request start;
  2. `warm()` must eagerly load it so a server can preload at startup and never
     pay the download cost inside a user request.

Both tests mock fastembed, so they never touch the network.
"""
import threading
import time

import pytest

import dealfinder.embed as embed
from dealfinder import dedup


def _install_fake_model(monkeypatch):
    """Replace fastembed.TextEmbedding with a slow-constructing counter and reset
    the module singleton to cold. The sleep widens the race window so an unlocked
    check-then-set reliably double-constructs."""
    calls = {"n": 0}

    class FakeModel:
        def __init__(self, name):
            calls["n"] += 1
            time.sleep(0.05)

        def embed(self, texts):
            return [[0.0] * embed_len for _ in texts]

    embed_len = 384
    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", FakeModel)
    monkeypatch.setattr(embed, "_model", None)
    return calls


def test_get_model_is_thread_safe_single_construction(monkeypatch):
    calls = _install_fake_model(monkeypatch)
    try:
        got = []
        threads = [threading.Thread(target=lambda: got.append(embed._get_model())) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # The lock must collapse 8 concurrent cold callers into ONE construction.
        assert calls["n"] == 1
        assert got and all(m is got[0] for m in got)
    finally:
        embed._model = None


def test_warm_eagerly_loads_the_model(monkeypatch):
    calls = _install_fake_model(monkeypatch)
    try:
        assert embed._model is None
        assert embed.warm() is True
        assert embed._model is not None
        assert calls["n"] == 1
        # idempotent: a second warm does not reconstruct.
        assert embed.warm() is True
        assert calls["n"] == 1
    finally:
        embed._model = None


def test_one_embedding_model_per_process(monkeypatch):
    made = []

    class Fake:
        def __init__(self, *a, **k): made.append(1)
        def embed(self, texts): return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr("fastembed.TextEmbedding", Fake)
    monkeypatch.setattr(embed, "_model", None)
    embed._get_model()
    dedup._embed(["a", "b"])
    assert len(made) == 1


class _CountingModel:
    """A stand-in for the fastembed model that records every text it embeds."""

    def __init__(self, seen):
        self.seen = seen

    def embed(self, texts):
        for t in texts:
            self.seen.append(t)
            yield [float(len(t)), 1.0]


@pytest.fixture
def fresh_embed_cache():
    embed._embed_cache.clear()
    yield
    embed._embed_cache.clear()


def test_embed_texts_cached_embeds_each_text_once(monkeypatch, fresh_embed_cache):
    seen = []
    monkeypatch.setattr(embed, "_get_model", lambda: _CountingModel(seen))
    start = embed._now()
    embed.embed_texts_cached(["a", "b"])
    embed.embed_texts_cached(["b", "c"])
    assert seen == ["a", "b", "c"]
    monkeypatch.setattr(embed, "_now", lambda: start + embed.EMBED_CACHE_TTL_S + 1)
    embed.embed_texts_cached(["a"])
    assert seen[-1] == "a"


def test_model_dir_is_honored(monkeypatch):
    # The production image bakes the model into DEALFINDER_MODEL_DIR so a cold start
    # never downloads it.
    seen = {}

    class Fake:
        def __init__(self, name, **kw):
            seen.update(kw)

    monkeypatch.setattr("fastembed.TextEmbedding", Fake)
    monkeypatch.setattr(embed, "_model", None)
    monkeypatch.setenv("DEALFINDER_MODEL_DIR", "/opt/models")
    embed._get_model()
    assert seen["cache_dir"] == "/opt/models"


def test_no_model_dir_keeps_the_default_cache(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, name, **kw):
            seen.update(kw)

    monkeypatch.setattr("fastembed.TextEmbedding", Fake)
    monkeypatch.setattr(embed, "_model", None)
    monkeypatch.delenv("DEALFINDER_MODEL_DIR", raising=False)
    embed._get_model()
    assert "cache_dir" not in seen
