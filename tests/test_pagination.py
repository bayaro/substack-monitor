import config


def endpoint(cli, server, **kwargs):
    config.CONFIG["t"] = {"url": f"{server.url}/x", **kwargs}


def test_plain_request(cli, server):
    server.handler = lambda req: (200, [{"id": 1, "n": {"k": 2}}], {})
    endpoint(cli, server)
    assert cli.__fetch("t") == [{"id": 1, "n_k": 2}]


def test_params_are_sent(cli, server):
    endpoint(cli, server, params={"public": "true"})
    cli.__fetch("t")
    assert server.requests[0]["query"] == {"public": ["true"]}


def test_offset_pagination_get(cli, server):
    data = list(range(5))
    server.handler = lambda req: (
        200,
        [{"v": v} for v in data[int(req["query"]["offset"][0]):][:int(req["query"]["limit"][0])]],
        {},
    )
    endpoint(cli, server, pagination="offset", limit=2)
    assert [r["v"] for r in cli.__fetch("t")] == [0, 1, 2, 3, 4]
    assert [r["query"]["offset"] for r in server.requests] == [["0"], ["2"], ["4"]]


def test_offset_pagination_stops_on_empty_page(cli, server):
    data = [1, 2]
    server.handler = lambda req: (
        200, [{"v": v} for v in data[int(req["query"]["offset"][0]):][:2]], {}
    )
    endpoint(cli, server, pagination="offset", limit=2)
    assert len(cli.__fetch("t")) == 2
    assert len(server.requests) == 2


def test_offset_pagination_post_with_items_field(cli, server):
    data = list(range(3))

    def handler(req):
        offset, limit = req["body"]["offset"], req["body"]["limit"]
        return 200, {"subscribers": [{"v": v} for v in data[offset:offset + limit]]}, {}

    server.handler = handler
    endpoint(cli, server, method="post", pagination="offset", limit=2,
             items_field="subscribers", body={"filters": {"a": 1}})
    assert [r["v"] for r in cli.__fetch("t")] == [0, 1, 2]
    assert all(r["method"] == "POST" for r in server.requests)
    assert server.requests[0]["body"] == {"filters": {"a": 1}, "limit": 2, "offset": 0}
    assert server.requests[1]["body"]["offset"] == 2


def cursor_handler(chain, server, max_requests=20):
    def handler(req):
        if len(server.requests) > max_requests:  # a runaway loop fails the test instead of hanging
            return 500, {}, {}
        cursor = req["query"].get("cursor", [None])[0]
        return 200, {"items": [{"at": cursor or "start"}], "nextCursor": chain.get(cursor)}, {}
    return handler


def test_cursor_pagination(cli, server):
    server.handler = cursor_handler({None: "c1", "c1": "c2", "c2": None}, server)
    endpoint(cli, server, pagination="cursor")
    assert [r["at"] for r in cli.__fetch("t")] == ["start", "c1", "c2"]


def test_cursor_pagination_stops_on_empty_items(cli, server):
    server.handler = lambda req: (200, {"items": [], "nextCursor": "again"}, {})
    endpoint(cli, server, pagination="cursor")
    assert cli.__fetch("t") == []
    assert len(server.requests) == 1


def test_repeated_cursor_stops_the_loop(cli, server, capsys):
    server.handler = cursor_handler({None: "c1", "c1": "c2", "c2": "c1"}, server)
    endpoint(cli, server, pagination="cursor")
    assert len(cli.__fetch("t")) == 3
    assert len(server.requests) == 3
    assert "cursor repeated" in capsys.readouterr().out


def test_dependency_user_id_is_substituted_in_url(cli, server):
    server.handler = lambda req: (200, [], {})
    config.CONFIG["t"] = {"url": f"{server.url}/profile/{{user_id}}"}
    open(config.CONFIG["user_id_file"], "w").write("42")
    cli.__fetch("t")
    assert server.requests[0]["path"] == "/profile/42"


def test_relative_url_uses_base_url(cli, server):
    config.CONFIG["base_url"] = server.url
    config.CONFIG["t"] = {"url": "api/v1/things"}
    cli.__fetch("t")
    assert server.requests[0]["path"] == "/api/v1/things"


def test_http_error_is_raised(cli, server):
    import pytest
    import requests
    server.handler = lambda req: (404, {}, {})
    endpoint(cli, server)
    with pytest.raises(requests.HTTPError):
        cli.__fetch("t")
