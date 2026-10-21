from pathlib import Path

import yaml

import config


def write_cache(cli, name, items):
    path = Path(config.CONFIG["cache_dir"]) / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(items), encoding="utf-8")


def read_data(cli, name):
    return yaml.safe_load((Path(config.CONFIG["data_dir"]) / f"{name}.yaml").read_text(encoding="utf-8"))


def test_collect_sorts_descending_by_sort_key(cli, capsys):
    config.CONFIG["cache"] = "read"
    config.CONFIG["t"] = {"url": "x", "sort_key": "date"}
    write_cache(cli, "t", [{"date": "2026-01-02"}, {"date": "2026-03-01"}, {"date": "2026-02-01"}])
    cli.__collect("t")
    assert [r["date"] for r in read_data(cli, "t")] == ["2026-03-01", "2026-02-01", "2026-01-02"]
    assert "Saved 3 records" in capsys.readouterr().out


def test_collect_without_sort_key_keeps_order(cli):
    config.CONFIG["cache"] = "read"
    config.CONFIG["t"] = {"url": "x"}
    write_cache(cli, "t", [{"v": 2}, {"v": 1}])
    cli.__collect("t")
    assert [r["v"] for r in read_data(cli, "t")] == [2, 1]


def test_collect_creates_data_dir_and_keeps_unicode(cli):
    config.CONFIG["cache"] = "read"
    config.CONFIG["t"] = {"url": "x"}
    write_cache(cli, "t", [{"text": "Дякую ❤"}])
    cli.__collect("t")
    raw = (Path(config.CONFIG["data_dir"]) / "t.yaml").read_text(encoding="utf-8")
    assert "Дякую ❤" in raw


def test_collect_end_to_end_with_server(cli, server):
    server.handler = lambda req: (200, {"items": [
        {"type": "comment", "comment": {"id": 1, "date": "2026-01-01"}},
        {"type": "post", "comment": None},
        {"type": "comment", "comment": {"id": 2, "date": "2026-02-01"}},
    ], "nextCursor": None}, {})
    config.CONFIG["t"] = {
        "url": f"{server.url}/feed",
        "pagination": "cursor",
        "filter": [{"type": "comment"}],
        "sort_key": "comment_date",
        "include": ["type", {"comment": ["id", "date"]}],
    }
    cli.__collect("t")
    assert read_data(cli, "t") == [
        {"type": "comment", "comment_id": 2, "comment_date": "2026-02-01"},
        {"type": "comment", "comment_id": 1, "comment_date": "2026-01-01"},
    ]
