import os
import time
from pathlib import Path

import pytest
import requests
import yaml

import config
import fetch


@pytest.fixture
def endpoint(env, server):
    server.handler = lambda req: (200, [{"id": 1}, {"id": 2}], {})
    config.CONFIG.endpoints["t"] = {"url": f"{server.url}/x"}
    return config.CONFIG.endpoints["t"]


def cache_path(env):
    return Path(config.CONFIG.cache_dir) / "t.yaml"


def write_cache(env, items, age_seconds=0):
    path = cache_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(items), encoding="utf-8")
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(path, (past, past))


def test_no_cache_mode_does_not_write_cache(env, server, endpoint):
    fetch.do_request("t")
    assert not cache_path(env).exists()


def test_write_mode_stores_raw_items(env, server, endpoint, capsys):
    config.CONFIG.cache = "write"
    endpoint["include"] = ["id"]
    config.CONFIG.endpoints["t"]["url"] = f"{server.url}/x"
    server.handler = lambda req: (200, [{"id": 1, "secret": "s"}], {})
    assert fetch.do_request("t") == [{"id": 1}]
    assert yaml.safe_load(cache_path(env).read_text(encoding="utf-8")) == [{"id": 1, "secret": "s"}]
    assert not cache_path(env).with_suffix(".yaml.tmp").exists()
    assert "cache written" in capsys.readouterr().out


def test_read_mode_uses_cache_and_skips_network(env, server, endpoint, capsys):
    config.CONFIG.cache = "read"
    endpoint["include"] = ["id"]
    write_cache(env, [{"id": 7, "other": 1}])
    assert fetch.do_request("t") == [{"id": 7}]
    assert server.requests == []
    assert "reading cache" in capsys.readouterr().out


def test_read_mode_applies_filter_and_columns(env, endpoint):
    config.CONFIG.cache = "read"
    endpoint.update(filter=[{"type": "c"}], exclude=["type"])
    write_cache(env, [{"type": "c", "id": 1}, {"type": "p", "id": 2}])
    assert fetch.do_request("t") == [{"id": 1}]


def test_auto_reads_fresh_cache(env, server, endpoint):
    config.CONFIG.cache = "auto"
    write_cache(env, [{"id": 9}], age_seconds=60)
    assert fetch.do_request("t") == [{"id": 9}]
    assert server.requests == []


def test_auto_refetches_stale_cache(env, server, endpoint):
    config.CONFIG.cache = "auto"
    write_cache(env, [{"id": 9}], age_seconds=11 * 60)
    assert fetch.do_request("t") == [{"id": 1}, {"id": 2}]
    assert len(server.requests) == 1
    assert yaml.safe_load(cache_path(env).read_text(encoding="utf-8")) == [{"id": 1}, {"id": 2}]


def test_auto_fetches_when_cache_missing(env, server, endpoint):
    config.CONFIG.cache = "auto"
    assert fetch.do_request("t") == [{"id": 1}, {"id": 2}]
    assert cache_path(env).exists()


def test_auto_age_is_configurable(env, server, endpoint):
    config.CONFIG.cache = "auto"
    config.CONFIG.cache_auto_age_minutes = 1
    write_cache(env, [{"id": 9}], age_seconds=120)
    assert fetch.do_request("t") == [{"id": 1}, {"id": 2}]


def test_failed_fetch_keeps_previous_cache(env, server, endpoint):
    config.CONFIG.cache = "write"
    write_cache(env, [{"id": "old"}])
    server.handler = lambda req: (500, {}, {})
    with pytest.raises(requests.HTTPError):
        fetch.do_request("t")
    assert yaml.safe_load(cache_path(env).read_text(encoding="utf-8")) == [{"id": "old"}]
