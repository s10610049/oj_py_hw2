"""Synthetic HTTP only; no source text, media, or credentials in these fixtures."""

import json

import httpx
import pytest

from scripts import cache_luogu as catalog

ROBOTS = "User-agent: *\nDisallow: /private"
ULA = "<html><body>Synthetic private-use policy</body></html>"


@pytest.fixture
def simulation(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "APPROVED_POLICIES",
        {
            url: catalog.digest(catalog.policy_text(url, body).encode())
            for url, body in [(catalog.ROBOTS_URL, ROBOTS), (catalog.ULA_URL, ULA)]
        },
    )
    state = {"now": 0.0, "requests": [], "overrides": {}}

    def sleep(seconds):
        state["now"] += seconds

    def handler(request):
        url = str(request.url)
        state["requests"].append((url, state["now"]))
        assert request.method == "GET"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        assert request.headers["user-agent"] == catalog.USER_AGENT
        if url in state["overrides"]:
            value = state["overrides"][url]
            if isinstance(value, Exception):
                raise value
            return value
        body = {
            catalog.ROBOTS_URL: ROBOTS,
            catalog.ULA_URL: ULA,
            **{
                url: f'<html><body>{key} 题目描述 Synthetic only <img src="/media.png"></body></html>'
                for key, url in catalog.PROBLEMS.items()
            },
        }[url]
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/html", "set-cookie": "anonymous=not-forwarded"},
        )

    def run(path):
        return catalog.collect(
            path, transport=httpx.MockTransport(handler), sleep=sleep, clock=lambda: state["now"]
        )

    return state, run


def test_whitelist_spacing_raw_cache_and_reuse(tmp_path, simulation):
    state, run = simulation
    result = run(tmp_path)
    assert result["status"] == "cached"
    assert [url for url, _ in state["requests"]] == [
        catalog.ROBOTS_URL,
        catalog.ULA_URL,
        *catalog.PROBLEMS.values(),
    ]
    assert [stamp for _, stamp in state["requests"]] == [0, 10, 20, 30]
    for key, record in result["problems"].items():
        assert record["license_status"] == "unknown" and record["judging_ready"] is False
        raw = (tmp_path / f"{key}.html").read_bytes()
        assert catalog.digest(raw) == record["sha256"]
        assert b'<img src="/media.png">' in raw
    assert run(tmp_path) == result and len(state["requests"]) == 4
    assert set(path.name for path in tmp_path.iterdir()) == {
        "manifest.json",
        "P1001.html",
        "P1002.html",
    }


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500, 503])
def test_refusal_or_failure_stops_without_retry(tmp_path, simulation, status):
    state, run = simulation
    first = catalog.PROBLEMS["P1001"]
    state["overrides"][first] = httpx.Response(status, headers={"location": "/elsewhere"})
    result = run(tmp_path)
    assert result["status"] == ("failed" if status >= 500 else "blocked")
    assert result["problems"]["P1001"]["http_status"] == status
    assert result["problems"]["P1002"]["retrieval_status"] == "not_attempted"
    assert not list(tmp_path.glob("*.html"))
    assert len(state["requests"]) == 3
    run(tmp_path)
    assert len(state["requests"]) == 3


@pytest.mark.parametrize("marker", catalog.CHALLENGES)
def test_challenge_is_not_cached(tmp_path, simulation, marker):
    state, run = simulation
    state["overrides"][catalog.PROBLEMS["P1001"]] = httpx.Response(
        200, text=f"<html>{marker}</html>", headers={"content-type": "text/html"}
    )
    assert run(tmp_path)["reason"] == "challenge_page"
    assert len(state["requests"]) == 3 and not list(tmp_path.glob("*.html"))


@pytest.mark.parametrize("url", [catalog.ROBOTS_URL, catalog.ULA_URL])
def test_policy_changes_stop_before_problems(tmp_path, simulation, url):
    state, run = simulation
    state["overrides"][url] = httpx.Response(200, text="Changed policy")
    assert run(tmp_path)["reason"] == "policy_changed_review_required"
    assert all("/problem/" not in target for target, _ in state["requests"])


def test_robots_disallow_is_checked_even_with_approved_digest(tmp_path, simulation, monkeypatch):
    state, run = simulation
    body = "User-agent: *\nDisallow: /problem/"
    monkeypatch.setitem(
        catalog.APPROVED_POLICIES, catalog.ROBOTS_URL, catalog.digest(body.encode())
    )
    state["overrides"][catalog.ROBOTS_URL] = httpx.Response(200, text=body)
    assert run(tmp_path)["reason"] == "robots_disallow"
    assert len(state["requests"]) == 1


@pytest.mark.parametrize(
    "problem_body",
    [b"{}", b"<html>Login required</html>", b"x" * 2_000_001],
    ids=["not-html", "login-page", "too-large"],
)
def test_bad_pages_are_not_success(tmp_path, simulation, problem_body):
    state, run = simulation
    state["overrides"][catalog.PROBLEMS["P1001"]] = httpx.Response(
        200, content=problem_body, headers={"content-type": "text/html"}
    )
    assert run(tmp_path)["status"] == "blocked"
    assert not list(tmp_path.glob("*.html"))


def test_timeout_has_no_automatic_retry(tmp_path, simulation):
    state, run = simulation
    state["overrides"][catalog.PROBLEMS["P1001"]] = httpx.ReadTimeout("synthetic")
    assert run(tmp_path)["reason"] == "ReadTimeout"
    assert len(state["requests"]) == 3


def test_corrupt_cache_is_rejected_without_fetch(tmp_path, simulation):
    state, run = simulation
    run(tmp_path)
    (tmp_path / "P1001.html").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        run(tmp_path)
    assert len(state["requests"]) == 4


def test_partial_success_is_preserved_when_second_problem_is_blocked(tmp_path, simulation):
    state, run = simulation
    state["overrides"][catalog.PROBLEMS["P1002"]] = httpx.Response(403)
    result = run(tmp_path)
    assert result["status"] == "blocked"
    assert result["problems"]["P1001"]["retrieval_status"] == "cached"
    assert result["problems"]["P1002"]["retrieval_status"] == "blocked"
    assert json.loads((tmp_path / "manifest.json").read_text())["judging_ready"] is False


@pytest.mark.parametrize("value", [[], {"status": "cached"}, {"schema_version": 1, "problems": {}}])
def test_incomplete_manifest_cannot_claim_cached_success(tmp_path, simulation, value):
    state, run = simulation
    (tmp_path / "manifest.json").write_text(json.dumps(value))
    with pytest.raises(ValueError, match="manifest"):
        run(tmp_path)
    assert not state["requests"]
