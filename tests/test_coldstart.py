"""scripts/coldstart.py: force a cold instance, then time the first request to each route."""

import importlib.util
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
