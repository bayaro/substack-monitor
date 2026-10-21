import os
import time

import pytest
import requests
import yaml

import config
import fetch


class Flaky:
    """Cursor feed c0 -> c1 -> c2 -> end that answers 500 for the request carrying `fail_at` once."""

    chain = {None: "c1", "c1": "c2", "c2": None}

    def __init__(self, fail_at):
        self.fail_at = fail_at

    def __call__(self, req):
        cursor = req["query"].get("cursor", [None])[0]
        if cursor == self.fail_at:
            return 500, {}, {}
        return 200, {"items": [{"at": cursor or "start"}], "nextCursor": self.chain[cursor]}, {}


@pytest.fixture
def feed(env, server):
    config.CONFIG.cache = "write"
    config.CONFIG.endpoints["t"] = {"url": f"{server.url}/x", "pagination": "cursor"}
    server.handler = Flaky(fail_at="c2")
    return server


def cursors(server):
    return [r["query"].get("cursor", [None])[0] for r in server.requests]


def test_failure_keeps_the_partial_cache_and_says_how_to_continue(env, feed, capsys):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    assert fetch.__cache_file("t").with_suffix(".yaml.tmp").exists()
    assert fetch.__progress_file("t").exists()
    assert not fetch.__cache_file("t").exists()
    assert "run again to continue" in capsys.readouterr().out


def test_resume_continues_from_the_saved_cursor(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    assert [r["at"] for r in fetch.fetch("t")] == ["start", "c1", "c2"]
    assert cursors(feed) == ["c2"]  # earlier pages are not fetched again
    assert [i["at"] for i in yaml.safe_load(fetch.__cache_file("t").read_text(encoding="utf-8"))] == ["start", "c1", "c2"]
    assert not fetch.__progress_file("t").exists()
    assert not fetch.__cache_file("t").with_suffix(".yaml.tmp").exists()


def test_force_starts_the_download_over(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    config.CONFIG.force = True
    assert len(fetch.fetch("t")) == 3
    assert cursors(feed) == [None, "c1", "c2"]
    assert not fetch.__progress_file("t").exists()


def test_a_normal_run_without_a_partial_one_starts_from_scratch(env, feed):
    feed.handler = Flaky(fail_at="never")
    assert len(fetch.fetch("t")) == 3
    assert cursors(feed) == [None, "c1", "c2"]


def test_partial_download_is_continued_even_when_no_cache_mode_is_given(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    config.CONFIG.cache = None
    feed.handler = Flaky(fail_at="never")
    assert len(fetch.fetch("t")) == 3
    assert fetch.__cache_file("t").exists()


def test_partial_download_is_continued_in_auto_mode_even_with_a_fresh_cache(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    fetch.__cache_file("t").write_text("- at: old\n", encoding="utf-8")  # fresh by age
    config.CONFIG.cache = "auto"
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    assert [r["at"] for r in fetch.do_request("t")] == ["start", "c1", "c2"]
    assert cursors(feed) == ["c2"]


def test_read_mode_never_continues_a_download(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    fetch.__cache_file("t").write_text("- at: old\n", encoding="utf-8")
    config.CONFIG.cache = "read"
    feed.requests.clear()
    assert [r["at"] for r in fetch.do_request("t")] == ["old"]
    assert feed.requests == []


def test_data_written_after_the_last_saved_batch_is_dropped_on_resume(env, feed):
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    with fetch.__cache_file("t").with_suffix(".yaml.tmp").open("a", encoding="utf-8") as f:
        f.write("- at: half-written\n  broken: [")
    feed.handler = Flaky(fail_at="never")
    assert [r["at"] for r in fetch.fetch("t")] == ["start", "c1", "c2"]


def test_offset_pagination_resumes_from_the_saved_offset(env, server):
    data = list(range(5))
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        offset = int(req["query"]["offset"][0])
        if calls["n"] == 3 and not calls.get("healed"):
            return 500, {}, {}
        return 200, [{"v": v} for v in data[offset:offset + 2]], {}

    server.handler = handler
    config.CONFIG.cache = "write"
    config.CONFIG.endpoints["t"] = {"url": f"{server.url}/x", "pagination": "offset", "limit": 2}
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    server.requests.clear()
    calls["healed"] = True
    assert [r["v"] for r in fetch.fetch("t")] == [0, 1, 2, 3, 4]
    assert [r["query"]["offset"] for r in server.requests] == [["4"]]


def interrupt_and_age(feed, minutes):
    """Fail the download of "t", let the server heal and make the partial download `minutes` old."""
    with pytest.raises(requests.HTTPError):
        fetch.fetch("t")
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    past = time.time() - minutes * 60
    os.utime(fetch.__progress_file("t"), (past, past))


def test_partial_download_within_the_age_limit_is_continued(env, feed):
    interrupt_and_age(feed, 120)
    assert len(fetch.fetch("t")) == 3
    assert cursors(feed) == ["c2"]


def test_older_partial_download_is_not_continued(env, feed, capsys):
    interrupt_and_age(feed, 240)
    assert len(fetch.fetch("t")) == 3
    assert cursors(feed) == [None, "c1", "c2"]
    assert "interrupted download is 240 min old (limit 180 min), starting over" in capsys.readouterr().out
    assert not fetch.__progress_file("t").exists()


def test_age_limit_is_configurable(env, feed):
    config.CONFIG.resume_max_age_minutes = 360
    interrupt_and_age(feed, 240)
    assert len(fetch.fetch("t")) == 3
    assert cursors(feed) == ["c2"]


def test_older_partial_download_does_not_hide_a_fresh_cache(env, feed):
    interrupt_and_age(feed, 240)
    fetch.__cache_file("t").write_text("- at: cached\n", encoding="utf-8")
    config.CONFIG.cache = "auto"
    assert [r["at"] for r in fetch.do_request("t")] == ["cached"]
    assert feed.requests == []
