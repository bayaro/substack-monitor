import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import yaml
import requests


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def __read_cookies():
    text = Path(CONFIG["cookie_file"]).read_text(encoding="utf-8").strip()
    cookies = {}
    for pair in text.split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep:
            cookies[name] = value
    return cookies


def __save_cookies(cookies):
    Path(CONFIG["cookie_file"]).write_text(
        "; ".join(f"{k}={v}" for k, v in cookies.items()), encoding="utf-8"
    )


def __request(url, params=None, headers=None, method="get", body=None):
    cookies = __read_cookies()
    response = getattr(requests, method)(
        url,
        params=params,
        json=body,
        headers={
            **CONFIG.get("headers", {}),
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
            **(headers or {}),
        },
        timeout=CONFIG.get("timeout", 30),
    )
    updated = {**cookies, **response.cookies.get_dict()}
    if updated != cookies:
        __save_cookies(updated)
    response.raise_for_status()
    return response.json()

def __flatten(item, prefix=""):
    record = {}
    for key, value in (item or {}).items():
        flat_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            record.update(__flatten(value, flat_key))
        else:
            record[flat_key] = value
    return record


def __traverse(item, spec, prefix="", mode="include"):
    if not isinstance(item, dict):
        return {}
    spec_map = {e: None for e in spec if isinstance(e, str)}
    for e in spec:
        if isinstance(e, dict):
            spec_map.update(e)
    record = {}
    for key, value in item.items():
        flat_key = f"{prefix}_{key}" if prefix else key
        subspec = spec_map.get(key)
        in_spec = key in spec_map
        if subspec:
            record.update(__traverse(value or {}, subspec, flat_key, mode))
        elif (mode == "include") == in_spec:
            record.update(__flatten(value, flat_key) if isinstance(value, dict) else {flat_key: value})
    return record


def __filter_columns(items, include=None, exclude=None):
    if exclude:
        return [__traverse(item, exclude, mode="exclude") for item in items]
    if include:
        return [__traverse(item, include) for item in items]
    return [__flatten(item) for item in items]


def __filter_items(items, endpoint):
    for condition in endpoint.get("filter") or []:
        items = [i for i in items if all(i.get(k) == v for k, v in condition.items())]
    return __filter_columns(items, endpoint.get("include"), endpoint.get("exclude"))


def __resolve_deps(deps):
    values = {}
    data_dir = Path(CONFIG["data_dir"])
    for placeholder, path in deps.items():
        parts = path.split(".")
        source_file = data_dir / f"{parts[0]}.yaml"
        with source_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for part in parts[1:]:
            if part.startswith("[") and part.endswith("]"):
                data = data[int(part[1:-1])]
            else:
                data = data[part]
        values[placeholder] = data
    return values


def __ensure_cookie():
    cookie_path = Path(CONFIG["cookie_file"])
    max_age_days = CONFIG.get("cookie_max_age_days", 1)
    needs_refresh = not cookie_path.exists()
    if not needs_refresh:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(cookie_path.stat().st_mtime, tz=timezone.utc)
        needs_refresh = age.days >= max_age_days
    if needs_refresh:
        print(
            "\nCookie is missing or expired. To get a fresh cookie:\n"
            "  1. Open your browser and go to substack.com\n"
            "  2. Open DevTools (F12) → Network tab\n"
            "  3. Reload the page, click any request to substack.com\n"
            "  4. In Request Headers, find 'Cookie' and copy its full value\n"
        )
        cookie = input("Paste cookie value: ").strip()
        cookie_path.write_text(cookie, encoding="utf-8")
        print(f"Saved to {cookie_path}\n")


def __cache_file(method):
    return Path(CONFIG["cache_dir"]) / f"{method}.yaml"


def __cache_mode(method):
    mode = CONFIG.get("cache")
    if mode != "auto":
        return mode
    cache_file = __cache_file(method)
    if cache_file.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        if age.total_seconds() < CONFIG.get("cache_auto_age_minutes", 10) * 60:
            return "read"
    return "write"


def __fetch(method):
    endpoint = CONFIG[method]

    raw_url = endpoint["url"]
    if not raw_url.startswith("http"):
        raw_url = f"{CONFIG['base_url']}/{raw_url}"

    deps = endpoint.get("dependencies", {})
    url = raw_url.format(**CONFIG, **(__resolve_deps(deps) if deps else {}))
    params = endpoint.get("params", {})
    http_method = endpoint.get("method", "get")
    body = endpoint.get("body", {})

    __ensure_cookie()
    extra_headers = {}

    cache_f = None
    cache_tmp = __cache_file(method).with_suffix(".yaml.tmp")
    if __cache_mode(method) == "write":
        cache_tmp.parent.mkdir(parents=True, exist_ok=True)
        cache_f = cache_tmp.open("w", encoding="utf-8")

    results = []

    def process(batch):
        if cache_f:
            for item in batch:
                cache_f.write(yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False))
        results.extend(__filter_items(batch, endpoint))

    try:
        if endpoint.get("pagination") == "offset":
            limit = endpoint.get("limit", 20)
            items_field = endpoint.get("items_field")
            offset = 0
            while True:
                if http_method == "post":
                    response = __request(url, body={**body, "limit": limit, "offset": offset}, headers=extra_headers, method=http_method)
                else:
                    response = __request(url, params={**params, "limit": limit, "offset": offset}, headers=extra_headers)
                batch = response.get(items_field, []) if items_field and isinstance(response, dict) else response
                if not batch:
                    break
                process(batch)
                offset += len(batch)
                if len(batch) < limit:
                    break
        elif endpoint.get("pagination") == "cursor":
            cursor_field = endpoint.get("cursor_field", "nextCursor")
            items_field = endpoint.get("items_field", "items")
            cursor = None
            while True:
                p = {**params, **({"cursor": cursor} if cursor else {})}
                response = __request(url, params=p, headers=extra_headers)
                batch = response.get(items_field, []) if isinstance(response, dict) else response
                if not batch:
                    break
                process(batch)
                cursor = response.get(cursor_field) if isinstance(response, dict) else None
                if not cursor:
                    break
        else:
            process(__request(url, params=params, headers=extra_headers))
    finally:
        if cache_f:
            cache_f.close()
    if cache_f:
        cache_tmp.replace(__cache_file(method))

    return results


def do_request(method):
    if __cache_mode(method) != "read":
        return __fetch(method)

    with __cache_file(method).open("r", encoding="utf-8") as f:
        return __filter_items(yaml.safe_load(f), CONFIG[method])


def __collect(method):
    data_dir = Path(CONFIG["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    sort_key = CONFIG[method].get("sort_key")
    result = do_request(method)
    if sort_key:
        result = sorted(result, key=lambda x: x.get(sort_key), reverse=True)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--account")
    parser.add_argument("-m", "--method", required=True)
    parser.add_argument("--cache", choices=["write", "read", "auto"])
    args = parser.parse_args()

    if args.account:
        CONFIG["account_name"] = args.account
    if args.cache:
        CONFIG["cache"] = args.cache

    if not CONFIG.get("account_name"):
        parser.error("account required: pass -a or set account_name in config.yaml")

    if args.method == "all":
        for method in [k for k, v in CONFIG.items() if isinstance(v, dict) and "url" in v]:
            __collect(method)
    else:
        __collect(args.method)


if __name__ == "__main__":
    CONFIG = load_config()
    main()
