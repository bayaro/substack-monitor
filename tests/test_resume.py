import pytest
import requests
import yaml


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
def feed(cli, server):
    cli.CONFIG["cache"] = "write"
    cli.CONFIG["t"] = {"url": f"{server.url}/x", "pagination": "cursor"}
    server.handler = Flaky(fail_at="c2")
    return server


def cursors(server):
    return [r["query"].get("cursor", [None])[0] for r in server.requests]


def test_failure_keeps_the_partial_cache_and_says_how_to_continue(cli, feed, capsys):
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    assert cli.__cache_file("t").with_suffix(".yaml.tmp").exists()
    assert cli.__progress_file("t").exists()
    assert not cli.__cache_file("t").exists()
    assert "run again with --resume" in capsys.readouterr().out


def test_resume_continues_from_the_saved_cursor(cli, feed):
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    cli.CONFIG["resume"] = True
    assert [r["at"] for r in cli.__fetch("t")] == ["start", "c1", "c2"]
    assert cursors(feed) == ["c2"]  # earlier pages are not fetched again
    assert [i["at"] for i in yaml.safe_load(cli.__cache_file("t").read_text(encoding="utf-8"))] == ["start", "c1", "c2"]
    assert not cli.__progress_file("t").exists()
    assert not cli.__cache_file("t").with_suffix(".yaml.tmp").exists()


def test_without_resume_the_download_starts_over(cli, feed):
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    feed.requests.clear()
    feed.handler = Flaky(fail_at="never")
    assert len(cli.__fetch("t")) == 3
    assert cursors(feed) == [None, "c1", "c2"]
    assert not cli.__progress_file("t").exists()


def test_resume_without_a_partial_run_starts_from_scratch(cli, feed, capsys):
    feed.handler = Flaky(fail_at="never")
    cli.CONFIG["resume"] = True
    assert len(cli.__fetch("t")) == 3
    assert "nothing to resume" in capsys.readouterr().out
    assert cursors(feed) == [None, "c1", "c2"]


def test_resume_works_even_when_no_cache_mode_is_given(cli, feed):
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    del cli.CONFIG["cache"]
    feed.handler = Flaky(fail_at="never")
    cli.CONFIG["resume"] = True
    assert len(cli.__fetch("t")) == 3
    assert cli.__cache_file("t").exists()


def test_data_written_after_the_last_saved_batch_is_dropped_on_resume(cli, feed):
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    with cli.__cache_file("t").with_suffix(".yaml.tmp").open("a", encoding="utf-8") as f:
        f.write("- at: half-written\n  broken: [")
    feed.handler = Flaky(fail_at="never")
    cli.CONFIG["resume"] = True
    assert [r["at"] for r in cli.__fetch("t")] == ["start", "c1", "c2"]


def test_offset_pagination_resumes_from_the_saved_offset(cli, server):
    data = list(range(5))
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        offset = int(req["query"]["offset"][0])
        if calls["n"] == 3 and not calls.get("healed"):
            return 500, {}, {}
        return 200, [{"v": v} for v in data[offset:offset + 2]], {}

    server.handler = handler
    cli.CONFIG["cache"] = "write"
    cli.CONFIG["t"] = {"url": f"{server.url}/x", "pagination": "offset", "limit": 2}
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
    server.requests.clear()
    calls["healed"] = True
    cli.CONFIG["resume"] = True
    assert [r["v"] for r in cli.__fetch("t")] == [0, 1, 2, 3, 4]
    assert [r["query"]["offset"] for r in server.requests] == [["4"]]
