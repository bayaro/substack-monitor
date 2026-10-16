import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def cookie_file(cli):
    return Path(cli.CONFIG["cookie_file"])


def age_file(path, seconds):
    past = time.time() - seconds
    os.utime(path, (past, past))


def test_fresh_cookie_does_not_prompt(cli, cookie_file, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("should not prompt"))
    cli.__ensure_cookie()
    assert cookie_file.read_text(encoding="utf-8") == "sid=abc"


def test_missing_cookie_prompts_and_saves(cli, cookie_file, monkeypatch, capsys):
    cookie_file.unlink()
    monkeypatch.setattr("builtins.input", lambda *a: "  a=1; b=2  ")
    cli.__ensure_cookie()
    assert cookie_file.read_text(encoding="utf-8") == "a=1; b=2"
    assert "DevTools" in capsys.readouterr().out


def test_stale_cookie_prompts(cli, cookie_file, monkeypatch):
    age_file(cookie_file, 2 * 86400)
    monkeypatch.setattr("builtins.input", lambda *a: "new=1")
    cli.__ensure_cookie()
    assert cookie_file.read_text(encoding="utf-8") == "new=1"


def test_max_age_is_configurable(cli, cookie_file, monkeypatch):
    cli.CONFIG["cookie_max_age_days"] = 5
    age_file(cookie_file, 2 * 86400)
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("should not prompt"))
    cli.__ensure_cookie()


def test_cookie_is_sent_with_every_request(cli, server):
    cli.__request(f"{server.url}/x")
    assert server.requests[0]["headers"]["Cookie"] == "sid=abc"


def test_set_cookie_updates_file(cli, cookie_file, server):
    server.handler = lambda req: (200, [], {"Set-Cookie": "sid=new; Path=/"})
    cli.__request(f"{server.url}/x")
    assert cookie_file.read_text(encoding="utf-8") == "sid=new"


def test_new_cookies_are_merged_and_old_ones_kept(cli, cookie_file, server):
    cookie_file.write_text("sid=abc; keep=1", encoding="utf-8")
    server.handler = lambda req: (200, [], {"Set-Cookie": "extra=2; Path=/"})
    cli.__request(f"{server.url}/x")
    assert cookie_file.read_text(encoding="utf-8") == "sid=abc; keep=1; extra=2"


def test_updated_cookie_is_used_by_next_request(cli, server):
    server.handler = lambda req: (200, [], {"Set-Cookie": "sid=new; Path=/"})
    cli.__request(f"{server.url}/x")
    cli.__request(f"{server.url}/x")
    assert server.requests[1]["headers"]["Cookie"] == "sid=new"


def test_cookie_file_untouched_when_nothing_changes(cli, cookie_file, server):
    age_file(cookie_file, 3600)
    before = cookie_file.stat().st_mtime
    cli.__request(f"{server.url}/x")
    assert cookie_file.stat().st_mtime == before


def test_cookie_is_saved_even_when_request_fails(cli, cookie_file, server):
    import requests
    server.handler = lambda req: (401, {}, {"Set-Cookie": "sid=refreshed; Path=/"})
    with pytest.raises(requests.HTTPError):
        cli.__request(f"{server.url}/x")
    assert cookie_file.read_text(encoding="utf-8") == "sid=refreshed"


def test_cookie_value_with_equals_sign_survives(cli, cookie_file):
    cookie_file.write_text("a=b==; c=d", encoding="utf-8")
    assert cli.__read_cookies() == {"a": "b==", "c": "d"}


def test_request_log_line(cli, server, capsys):
    cli.__request(f"{server.url}/x", params={"limit": 2})
    out = capsys.readouterr().out
    assert out.startswith("GET ") and "/x?limit=2 -> 200 in " in out
    assert "sid=abc" not in out


def test_post_body_is_logged(cli, server, capsys):
    cli.__request(f"{server.url}/x", method="post", body={"limit": 5})
    assert 'body={"limit": 5} -> 200' in capsys.readouterr().out
