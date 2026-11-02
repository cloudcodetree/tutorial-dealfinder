"""scripts/healthchecks_setup.py: the uptime check, created idempotently, ping URLs never printed."""
import importlib.util
import json
from pathlib import Path

import httpx
import respx

spec = importlib.util.spec_from_file_location("healthchecks_setup", Path("scripts/healthchecks_setup.py"))
healthchecks_setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(healthchecks_setup)

API = "https://healthchecks.io/api/v3/checks/"


def _created(req):
    return httpx.Response(201, json={"ping_url": "https://hc-ping.com/" + json.loads(req.content)["name"]})


@respx.mock
def test_setup_creates_the_uptime_check_idempotently(tmp_path):
    route = respx.post(API).mock(side_effect=_created)
    healthchecks_setup.run(api_key="k", out=tmp_path / "pings.json")
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert [b["name"] for b in bodies] == ["dealfinder-uptime"]
    assert bodies[0]["unique"] == ["name"] and bodies[0]["channels"] == "*"
    assert (bodies[0]["timeout"], bodies[0]["grace"]) == (600, 1200)
    assert route.calls[0].request.headers["X-Api-Key"] == "k"


@respx.mock
def test_ping_urls_go_to_the_file_never_to_stdout(tmp_path, capsys):
    respx.post(API).mock(side_effect=_created)
    healthchecks_setup.run(api_key="k", out=tmp_path / "pings.json")
    assert json.loads((tmp_path / "pings.json").read_text()) == {"dealfinder-uptime": "https://hc-ping.com/dealfinder-uptime"}
    assert "hc-ping.com" not in capsys.readouterr().out


def test_dry_run_sends_nothing(tmp_path, capsys):
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(API)
        healthchecks_setup.run(api_key="k", out=tmp_path / "pings.json", dry_run=True)
    assert route.call_count == 0 and "dealfinder-uptime" in capsys.readouterr().out


@respx.mock
def test_a_refused_key_fails_with_the_status_only(tmp_path):
    respx.post(API).mock(return_value=httpx.Response(401, json={"error": "wrong api key"}))
    try:
        healthchecks_setup.run(api_key="k", out=tmp_path / "pings.json")
    except RuntimeError as e:
        assert "401" in str(e) and "k" not in str(e).replace("check", "")
    else:
        raise AssertionError("expected a RuntimeError")
