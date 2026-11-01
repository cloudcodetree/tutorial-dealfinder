"""scripts/coldstart.py: force a cold instance, then time the first request to each route."""

import importlib.util
import io
import urllib.error
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("coldstart", Path("scripts/coldstart.py"))
coldstart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coldstart)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _fakes(latencies):
    """latencies: per run, (healthz seconds, readyz seconds)."""
    events, clock = [], FakeClock()
    pending = [s for pair in latencies for s in pair]

    def redeploy():
        events.append("redeploy")

    def wait():
        events.append("wait")

    def get(url):
        events.append(url.rsplit("/", 1)[-1])
        clock.t += pending.pop(0)

    return events, clock, redeploy, wait, get


def test_each_run_redeploys_waits_out_the_warm_instance_then_times_both_routes():
    events, clock, redeploy, wait, get = _fakes([(4.0, 0.5), (5.0, 0.4)])
    runs = coldstart.measure("https://x/api", runs=2, redeploy=redeploy, wait=wait, get=get, clock=clock)
    assert [pytest.approx(r) for r in runs] == [(4.0, 0.5), (5.0, 0.4)]
    assert events == ["redeploy", "wait", "health", "readyz"] * 2


def test_report_prints_each_run_and_the_median(capsys):
    assert coldstart.report([(4.0, 0.5), (6.0, 0.7), (5.0, 0.4)]) == 0
    out = capsys.readouterr().out
    assert "run 1: health 4.0s readyz 0.5s" in out and "median: health 5.0s readyz 0.5s" in out


def test_a_cold_healthz_over_10s_fails():
    assert coldstart.report([(4.0, 0.5), (10.5, 0.5)]) == 1


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b""


def _opener(status, seen=None):
    def open_(req, timeout):
        if seen is not None:
            seen.append(req)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "x", {}, io.BytesIO(b"error code: 1010"))
        return _Resp(status)
    return open_


def test_get_names_itself_so_cloudflare_does_not_block_it():
    # Cloudflare answers Python's default User-Agent with 403, error 1010. The first
    # live run timed that block page (0.1 s) and reported it as a cold start.
    seen = []
    coldstart._get("https://x/api/health", opener=_opener(200, seen))
    assert seen[0].get_header("User-agent") == coldstart.USER_AGENT


def test_get_fails_the_run_when_health_is_not_200():
    with pytest.raises(RuntimeError, match="403"):
        coldstart._get("https://x/api/health", opener=_opener(403))


def test_get_accepts_readyz_503_but_not_a_block():
    coldstart._get("https://x/api/readyz", opener=_opener(503))
    with pytest.raises(RuntimeError, match="403"):
        coldstart._get("https://x/api/readyz", opener=_opener(403))
