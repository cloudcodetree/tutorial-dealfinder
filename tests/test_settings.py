"""Production settings: one JSON secret expands at startup, and no .env file in production."""

import importlib
import os

import pytest

from dealfinder import settings


def test_load_secrets_expands_but_never_overrides(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "real")
    # setenv first so monkeypatch restores the variable, even though load_secrets sets it.
    monkeypatch.setenv("EDGE_SHARED_SECRET", "x")
    monkeypatch.delenv("EDGE_SHARED_SECRET")
    monkeypatch.setenv("DEALFINDER_SECRETS_JSON", '{"BESTBUY_API_KEY": "blob", "EDGE_SHARED_SECRET": "s1"}')
    settings.load_secrets()
    assert (os.environ["BESTBUY_API_KEY"], os.environ["EDGE_SHARED_SECRET"]) == ("real", "s1")


def test_bad_json_fails_without_echoing(monkeypatch):
    monkeypatch.setenv("DEALFINDER_SECRETS_JSON", "not-json-hunter2")
    with pytest.raises(RuntimeError) as e:
        settings.load_secrets()
    assert "hunter2" not in str(e.value)


def test_secrets_must_be_an_object_of_strings(monkeypatch):
    monkeypatch.setenv("DEALFINDER_SECRETS_JSON", '["hunter2"]')
    with pytest.raises(RuntimeError, match="not a JSON object") as e:
        settings.load_secrets()
    assert "hunter2" not in str(e.value)


def test_no_secrets_variable_is_a_no_op(monkeypatch):
    monkeypatch.delenv("DEALFINDER_SECRETS_JSON", raising=False)
    settings.load_secrets()


def test_production_never_reads_dotenv(monkeypatch):
    calls = []
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: calls.append(1))
    monkeypatch.setenv("DEALFINDER_ENV", "production")
    importlib.reload(importlib.import_module("dealfinder"))
    assert calls == []
    monkeypatch.delenv("DEALFINDER_ENV")
    importlib.reload(importlib.import_module("dealfinder"))
    assert calls == [1]          # outside production the course's .env still loads


def test_empty_secrets_variable_is_a_no_op(monkeypatch):
    # A blank line copied from the example env file must not crash a reloaded worker.
    monkeypatch.setenv("DEALFINDER_SECRETS_JSON", "")
    settings.load_secrets()
