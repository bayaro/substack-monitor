import importlib.util

from conftest import ROOT


def test_the_real_config_is_valid(cli):
    assert cli.__validate_config(cli.load_config(ROOT / "config.yaml")) == []


def test_unknown_endpoint_key_is_reported_with_a_hint(cli):
    errors = cli.__validate_config({"posts": {"url": "u", "exlcude": ["a"]}})
    assert errors == ["posts: unknown key 'exlcude', did you mean 'exclude'?"]


def test_unknown_key_without_a_close_match_has_no_hint(cli):
    assert cli.__validate_config({"posts": {"url": "u", "zzzzzz": 1}}) == ["posts: unknown key 'zzzzzz'"]


def test_unknown_global_key_is_reported(cli):
    errors = cli.__validate_config({"cookie_fil": "x"})
    assert errors == ["config: unknown key 'cookie_fil', did you mean 'cookie_file'?"]


def test_known_globals_are_accepted(cli):
    assert cli.__validate_config({"timeout": 5, "headers": {"A": "b"}, "cookie_file": "c"}) == []


def test_underscore_keys_are_inactive(cli):
    config = {"_old": {"url": "u"}, "posts": {"url": "u", "_include": ["id"]}, "_note": 1}
    assert cli.__validate_config(config) == []


def test_section_without_url_is_reported(cli):
    errors = cli.__validate_config({"heders": {"User-Agent": "x"}})
    assert len(errors) == 1 and "did you mean 'headers'" in errors[0] and "has no url" in errors[0]


def test_bad_method_and_pagination(cli):
    errors = cli.__validate_config({"a": {"url": "u", "method": "put", "pagination": "page"}})
    assert errors == ["a: method must be get or post, not 'put'", "a: pagination must be offset or cursor, not 'page'"]


def test_list_keys_must_be_lists(cli):
    errors = cli.__validate_config({"a": {"url": "u", "include": "id", "filter": {"type": "x"}}})
    assert errors == ["a: include must be a list", "a: filter must be a list"]


def test_delta_must_be_a_column(cli):
    errors = cli.__validate_config({"a": {"url": "u", "columns": ["date", "n"], "delta": "m"}})
    assert errors == ["a: delta 'm' is not one of columns"]


def test_all_problems_are_reported_at_once(cli):
    errors = cli.__validate_config({"a": {"url": "u", "mehtod": "get", "pagination": "x"}})
    assert len(errors) == 2
