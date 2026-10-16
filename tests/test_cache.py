import os
import time
from pathlib import Path

import pytest
import requests
import yaml


@pytest.fixture
def endpoint(cli, server):
    server.handler = lambda req: (200, [{"id": 1}, {"id": 2}], {})
    cli.CONFIG["t"] = {"url": f"{server.url}/x"}
    return cli.CONFIG["t"]


def cache_path(cli):
    return Path(cli.CONFIG["cache_dir"]) / "t.yaml"


def write_cache(cli, items, age_seconds=0):
    path = cache_path(cli)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(items), encoding="utf-8")
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(path, (past, past))


def test_no_cache_mode_does_not_write_cache(cli, server, endpoint):
    cli.do_request("t")
    assert not cache_path(cli).exists()


def test_write_mode_stores_raw_items(cli, server, endpoint, capsys):
    cli.CONFIG["cache"] = "write"
    endpoint["include"] = ["id"]
    cli.CONFIG["t"]["url"] = f"{server.url}/x"
    server.handler = lambda req: (200, [{"id": 1, "secret": "s"}], {})
    assert cli.do_request("t") == [{"id": 1}]
    assert yaml.safe_load(cache_path(cli).read_text(encoding="utf-8")) == [{"id": 1, "secret": "s"}]
    assert not cache_path(cli).with_suffix(".yaml.tmp").exists()
    assert "cache written" in capsys.readouterr().out


def test_read_mode_uses_cache_and_skips_network(cli, server, endpoint, capsys):
    cli.CONFIG["cache"] = "read"
    endpoint["include"] = ["id"]
    write_cache(cli, [{"id": 7, "other": 1}])
    assert cli.do_request("t") == [{"id": 7}]
    assert server.requests == []
    assert "reading cache" in capsys.readouterr().out


def test_read_mode_applies_filter_and_columns(cli, endpoint):
    cli.CONFIG["cache"] = "read"
    endpoint.update(filter=[{"type": "c"}], exclude=["type"])
    write_cache(cli, [{"type": "c", "id": 1}, {"type": "p", "id": 2}])
    assert cli.do_request("t") == [{"id": 1}]


def test_auto_reads_fresh_cache(cli, server, endpoint):
    cli.CONFIG["cache"] = "auto"
    write_cache(cli, [{"id": 9}], age_seconds=60)
    assert cli.do_request("t") == [{"id": 9}]
    assert server.requests == []


def test_auto_refetches_stale_cache(cli, server, endpoint):
    cli.CONFIG["cache"] = "auto"
    write_cache(cli, [{"id": 9}], age_seconds=11 * 60)
    assert cli.do_request("t") == [{"id": 1}, {"id": 2}]
    assert len(server.requests) == 1
    assert yaml.safe_load(cache_path(cli).read_text(encoding="utf-8")) == [{"id": 1}, {"id": 2}]


def test_auto_fetches_when_cache_missing(cli, server, endpoint):
    cli.CONFIG["cache"] = "auto"
    assert cli.do_request("t") == [{"id": 1}, {"id": 2}]
    assert cache_path(cli).exists()


def test_auto_age_is_configurable(cli, server, endpoint):
    cli.CONFIG["cache"] = "auto"
    cli.CONFIG["cache_auto_age_minutes"] = 1
    write_cache(cli, [{"id": 9}], age_seconds=120)
    assert cli.do_request("t") == [{"id": 1}, {"id": 2}]


def test_failed_fetch_keeps_previous_cache(cli, server, endpoint):
    cli.CONFIG["cache"] = "write"
    write_cache(cli, [{"id": "old"}])
    server.handler = lambda req: (500, {}, {})
    with pytest.raises(requests.HTTPError):
        cli.do_request("t")
    assert yaml.safe_load(cache_path(cli).read_text(encoding="utf-8")) == [{"id": "old"}]
