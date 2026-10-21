from pathlib import Path

import pytest

import config
import fetch

USERS = [
    {"id": 1, "handle": "alice", "name": "Alice"},
    {"id": 2, "handle": "bob", "name": "Bob"},
]


def answers(monkeypatch, *values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda *a: next(it))


def test_saved_user_id_is_used_without_prompt(cli, monkeypatch):
    Path(config.CONFIG["user_id_file"]).write_text("42\n", encoding="utf-8")
    monkeypatch.setattr(fetch, "do_request",lambda m: pytest.fail("should not fetch users"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("should not prompt"))
    assert fetch.__ensure_user_id() == "42"


def test_single_user_is_listed_and_enter_accepts_it(cli, monkeypatch, capsys):
    monkeypatch.setattr(fetch, "do_request",lambda m: USERS[:1])
    answers(monkeypatch, "")
    assert fetch.__ensure_user_id() == "1"
    out = capsys.readouterr().out
    assert "1  @alice  Alice" in out
    assert Path(config.CONFIG["user_id_file"]).read_text(encoding="utf-8") == "1"


def test_several_users_require_a_choice(cli, monkeypatch, capsys):
    monkeypatch.setattr(fetch, "do_request",lambda m: USERS)
    answers(monkeypatch, "2")
    assert fetch.__ensure_user_id() == "2"
    out = capsys.readouterr().out
    assert "@alice" in out and "@bob" in out
    assert Path(config.CONFIG["user_id_file"]).read_text(encoding="utf-8") == "2"


def test_empty_answer_is_rejected_when_several_users(cli, monkeypatch):
    monkeypatch.setattr(fetch, "do_request",lambda m: USERS)
    answers(monkeypatch, "", "1")
    assert fetch.__ensure_user_id() == "1"


def test_unknown_id_is_asked_again(cli, monkeypatch):
    monkeypatch.setattr(fetch, "do_request",lambda m: USERS[:1])
    answers(monkeypatch, "99", "1")
    assert fetch.__ensure_user_id() == "1"


def test_no_users_raises(cli, monkeypatch):
    monkeypatch.setattr(fetch, "do_request",lambda m: [])
    with pytest.raises(RuntimeError, match="no users"):
        fetch.__ensure_user_id()
    assert not Path(config.CONFIG["user_id_file"]).exists()
