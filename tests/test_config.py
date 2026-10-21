import pytest
import yaml

import config
from conftest import ROOT

REQUIRED = {"account_name": "a", "base_url": "https://x"}


def check(cfg):
    """validate_config on a config that already has the required global settings."""
    return config.validate_config({**REQUIRED, **cfg})


def test_the_real_config_is_valid():
    config.load_config(ROOT / "config.yaml")
    assert "posts" in config.CONFIG.endpoints


def test_unknown_endpoint_key_is_reported_with_a_hint():
    errors = check({"posts": {"url": "u", "exlcude": ["a"]}})
    assert errors == ["posts: unknown key 'exlcude', did you mean 'exclude'?"]


def test_unknown_key_without_a_close_match_has_no_hint():
    assert check({"posts": {"url": "u", "zzzzzz": 1}}) == ["posts: unknown key 'zzzzzz'"]


def test_unknown_global_key_is_reported():
    errors = check({"cookie_fil": "x"})
    assert errors == ["config: unknown key 'cookie_fil', did you mean 'cookie_file'?"]


def test_known_globals_are_accepted():
    assert check({"timeout": 5, "headers": {"A": "b"}, "cookie_file": "c"}) == []


def test_underscore_keys_are_inactive():
    cfg = {"_old": {"url": "u"}, "posts": {"url": "u", "_include": ["id"]}, "_note": 1}
    assert check(cfg) == []


def test_section_without_url_is_reported():
    errors = check({"heders": {"User-Agent": "x"}})
    assert len(errors) == 1 and "did you mean 'headers'" in errors[0] and "has no url" in errors[0]


def test_bad_method_and_pagination():
    errors = check({"a": {"url": "u", "method": "put", "pagination": "page"}})
    assert errors == ["a: method must be get or post, not 'put'", "a: pagination must be offset or cursor, not 'page'"]


def test_list_keys_must_be_lists():
    errors = check({"a": {"url": "u", "include": "id", "filter": {"type": "x"}}})
    assert errors == ["a: include must be a list", "a: filter must be a list"]


def test_delta_must_be_a_column():
    errors = check({"a": {"url": "u", "columns": ["date", "n"], "delta": "m"}})
    assert errors == ["a: delta 'm' is not one of columns"]


def test_all_problems_are_reported_at_once():
    errors = check({"a": {"url": "u", "mehtod": "get", "pagination": "x"}})
    assert len(errors) == 2


@pytest.mark.parametrize("missing", ["account_name", "base_url"])
def test_settings_without_a_default_are_required(missing):
    cfg = {k: v for k, v in REQUIRED.items() if k != missing}
    assert config.validate_config(cfg) == [f"config: {missing} is required"]


def test_empty_required_setting_counts_as_missing():
    assert config.validate_config({**REQUIRED, "account_name": ""}) == ["config: account_name is required"]


def test_load_fills_defaults_globals_and_endpoints():
    cfg = config.Config()
    cfg.load({**REQUIRED, "timeout": 5, "posts": {"url": "u"}, "_off": {"url": "x"}})
    assert cfg.account_name == "a"
    assert cfg.timeout == 5
    assert cfg.rate_limit_retries == config.GLOBAL_KEYS["rate_limit_retries"]
    assert cfg.endpoints == {"posts": {"url": "u"}}
    assert cfg.cache is None and cfg.force is False


def test_defaults_are_not_shared_between_instances():
    first, second = config.Config(), config.Config()
    first.headers["A"] = "b"
    assert second.headers == {} and config.GLOBAL_KEYS["headers"] == {}


def test_load_config_raises_with_every_problem(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"posts": {"url": "u", "exlcude": []}}), encoding="utf-8")
    with pytest.raises(config.ConfigError) as error:
        config.load_config(path)
    message = str(error.value)
    assert "account_name is required" in message and "base_url is required" in message
    assert "did you mean 'exclude'" in message


def test_failed_load_leaves_config_untouched(tmp_path):
    config.CONFIG.reset()
    config.CONFIG.timeout = 99
    path = tmp_path / "config.yaml"
    path.write_text("posts: {url: u}\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load_config(path)
    assert config.CONFIG.timeout == 99
