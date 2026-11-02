"""The one course lab at /lab: every course mode, one API base, retired entry points."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from dealfinder import live_sources, serve
from dealfinder.serve import app

client = TestClient(app)

STATIC = Path(serve.__file__).parent / "static"
LAB_MODES = {"snapshot", "deals", "stream", "watchlist", "semantic", "ask", "context", "review", "dataset",
             "pipeline", "models", "tracking", "evals", "mlops", "safety", "compliance",
             "inference", "ops", "auth", "billing", "suggestions"}
COURSE_ENDPOINTS = ["/ranked", "/search/stream", "/watchlist", "/semantic", "/ask_agentic", "/context",
                    "/review", "/dataset", "/pipeline", "/models", "/tracking", "/evals", "/mlops",
                    "/safety", "/compliance", "/inference", "/ops", "/auth", "/billing", "/suggestions",
                    "/sources", "/config.json"]


def _js():
    r = client.get("/lab/lab.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    return r.text


def test_lab_holds_every_course_mode():
    assert set(re.findall(r'data-mode="([a-z]+)"', client.get("/lab").text)) == LAB_MODES


def test_lab_calls_every_course_endpoint():
    js = _js()
    assert [ep for ep in COURSE_ENDPOINTS if ep not in js] == []


def test_lab_requests_all_go_through_the_api_base():
    js = _js()
    assert not re.search(r"""(fetch|EventSource)\(\s*[`'"]/""", js)


def test_lab_api_base_direct_and_behind_the_edge():
    assert '<meta name="api-base" content="">' in client.get("/lab").text
    assert '<meta name="api-base" content="/api">' in client.get("/lab", headers={"X-DealFinder-Edge": "x"}).text


def test_old_entry_points_redirect_to_lab():
    for path in ("/", "/redesign"):
        r = client.get(path, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (301, "/lab")


def test_course_pages_are_retired():
    assert not (STATIC / "index.html").exists() and not (STATIC / "redesign.html").exists()


def test_lab_supports_deep_links_and_a_ready_flag():
    js = _js()
    assert "URLSearchParams(location.search)" in js
    assert re.search(r"dataset\.ready\s*=\s*['\"]true['\"]", js)


def test_lab_assets_are_allowlisted():
    assert client.get("/lab/lab.css").headers["content-type"].startswith("text/css")
    assert client.get("/lab/%2e%2e%2fserve.py").status_code == 404
    assert client.get("/lab/notes.txt").status_code == 404


def test_every_lab_mode_has_a_lesson_entry():
    lessons = client.get("/lab/lessons.json").json()
    assert set(lessons) == LAB_MODES
    assert all(set(v) == {"part", "slug", "live"} and v["live"] is False for v in lessons.values())


class _Off:
    name = "BestBuy"

    def available(self):
        return False


def test_lab_marks_live_data_off_without_a_source(monkeypatch):
    # Plan 4, "Launch without Best Buy": production has no key, so the lab says so.
    monkeypatch.setattr(live_sources, "enabled_sources", lambda names=None: [_Off()])
    assert '<meta name="live-data" content="off">' in client.get("/lab").text


def test_lab_marks_live_data_on_with_a_source(monkeypatch):
    class _On(_Off):
        def available(self):
            return True
    monkeypatch.setattr(live_sources, "enabled_sources", lambda names=None: [_Off(), _On()])
    assert '<meta name="live-data" content="on">' in client.get("/lab").text


def test_lab_says_why_live_modes_are_off():
    js = _js()
    assert "Live store data is off until DealFinder has a Best Buy API key." in js


def test_lab_loads_no_third_party_script_without_live_data(monkeypatch):
    # The privacy page says the site loads nothing from other companies. With no live
    # data there is no sign-in, so the lab drops the supabase-js tag from jsDelivr.
    monkeypatch.setattr(live_sources, "enabled_sources", lambda names=None: [_Off()])
    html = client.get("/lab").text
    assert "cdn.jsdelivr.net" not in html and "<script" in html


def test_lab_keeps_the_pinned_sign_in_script_with_live_data(monkeypatch):
    class _On(_Off):
        def available(self):
            return True
    monkeypatch.setattr(live_sources, "enabled_sources", lambda names=None: [_On()])
    assert 'src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js" integrity="sha384-' \
        in client.get("/lab").text


def test_lab_labels_model_written_answers():
    js = _js()
    assert "d.ai_written" in js and "AI-written" in js
