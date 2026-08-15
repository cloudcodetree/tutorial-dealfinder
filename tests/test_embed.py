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

import dealfinder.embed as embed


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
