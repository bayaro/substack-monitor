import argparse
from datetime import datetime, timezone
from pathlib import Path
import yaml

import config
import request


def __flatten(item, prefix=""):
    record = {}
    for key, value in (item or {}).items():
        flat_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            record.update(__flatten(value, flat_key))
        else:
            record[flat_key] = value
    return record


def __is_selector(key):
    return isinstance(key, str) and key.startswith("[") and key.endswith("]")


def __traverse_list(items, spec, prefix, mode):
    # spec entries pick list elements by a quoted bracket selector: "[first]", "[last]",
    # "[0]", "[-2]" or "[*]" for all. Columns: <prefix>_<first|last|index>_<field>
    record = {}
    for entry in spec:
        for selector, subspec in (entry if isinstance(entry, dict) else {entry: None}).items():
            text = str(selector)
            if not (text.startswith("[") and text.endswith("]")):
                raise ValueError(f"list selector must be bracketed, e.g. \"[last]\": {selector!r} under {prefix}")
            name = text[1:-1]
            if name == "*":
                picks = list(range(len(items)))
            elif name in ("first", "last"):
                picks = [0 if name == "first" else len(items) - 1] if items else []
            else:
                idx = int(name)
                picks = [idx % len(items)] if items and -len(items) <= idx < len(items) else []
            for idx in picks:
                label = name if name in ("first", "last") else idx
                key = f"{prefix}_{label}"
                if subspec:
                    record.update(__traverse(items[idx], subspec, key, mode))
                else:
                    value = items[idx]
                    record.update(__flatten(value, key) if isinstance(value, dict) else {key: value})
    return record


def __traverse(item, spec, prefix="", mode="include"):
    if not isinstance(item, dict):
        return {}
    spec_map = {e: None for e in spec if isinstance(e, str)}
    for e in spec:
        if isinstance(e, dict):
            spec_map.update(e)
    where = prefix or "<root>"
    for key in spec_map:
        if __is_selector(key):
            reason = "list selectors are only supported in include" if mode == "exclude" else "value is not a list"
            raise ValueError(f"list selector {key!r} under {where}: {reason}")
    record = {}
    for key, value in item.items():
        flat_key = f"{prefix}_{key}" if prefix else key
        subspec = spec_map.get(key)
        in_spec = key in spec_map
        if subspec and mode == "include" and isinstance(value, list):
            record.update(__traverse_list(value, subspec, flat_key, mode))
        elif subspec and isinstance(value, list):
            if any(__is_selector(k) for e in subspec for k in (e if isinstance(e, dict) else {e: None})):
                raise ValueError(f"list selectors are only supported in include (under {flat_key!r})")
            raise ValueError(f"exclude cannot look inside the list {flat_key!r}; exclude the whole key instead")
        elif subspec:
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
    columns = endpoint.get("columns")
    if columns:  # rows are positional lists, e.g. [date, value]: name them
        items = [dict(zip(columns, row)) for row in items]
    delta = endpoint.get("delta")
    if delta:  # change versus the previous row, in ascending sort_key order
        items = sorted(items, key=lambda i: i[endpoint["sort_key"]]) if endpoint.get("sort_key") else items
        previous = None
        for item in items:
            value = item.get(delta)
            item[f"{delta}_delta"] = None if previous is None or value is None else value - previous
            previous = value
    for condition in endpoint.get("filter") or []:
        items = [i for i in items if all(i.get(k) == v for k, v in condition.items())]
    records = __filter_columns(items, endpoint.get("include"), endpoint.get("exclude"))
    return [{k: v for k, v in record.items() if v is not None and v != ""} for record in records]


def __ensure_user_id():
    user_id_path = Path(config.CONFIG["user_id_file"])
    if user_id_path.exists():
        return user_id_path.read_text(encoding="utf-8").strip()
    users = do_request("users")
    if not users:
        raise RuntimeError("users endpoint returned no users, cannot determine user_id")
    print("\nPublication users:")
    for user in users:
        print(f"  {user['id']}  @{user.get('handle')}  {user.get('name')}")
    by_id = {str(user["id"]): user for user in users}
    default = str(users[0]["id"]) if len(users) == 1 else None
    prompt = f"Enter user id to use [{default}]: " if default else "Enter user id to use: "
    answer = input(prompt).strip() or default
    while answer not in by_id:
        answer = input("Unknown id, try again: ").strip() or default
    chosen = by_id[answer]
    user_id_path.write_text(str(chosen["id"]), encoding="utf-8")
    print(f"Saved user_id {chosen['id']} (@{chosen.get('handle')}) to {user_id_path}\n")
    return str(chosen["id"])


def __cache_file(method):
    return Path(config.CONFIG["cache_dir"]) / f"{method}.yaml"


def __progress_file(method):
    # where an interrupted download stands: next cursor/offset and the cache size that matches it
    return __cache_file(method).with_suffix(".yaml.progress")


def __cache_mode(method):
    mode = config.CONFIG.get("cache")
    if mode != "read" and not config.CONFIG.get("force") and __progress_file(method).exists():
        return "write"  # an interrupted download is continued, whatever the cache age
    if mode != "auto":
        return mode
    cache_file = __cache_file(method)
    if cache_file.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        if age.total_seconds() < config.CONFIG.get("cache_auto_age_minutes", 10) * 60:
            return "read"
    return "write"


def __fetch(method):
    endpoint = config.CONFIG[method]

    raw_url = endpoint["url"]
    if not raw_url.startswith("http"):
        raw_url = f"{config.CONFIG['base_url']}/{raw_url}"

    values = {}
    if "{user_id}" in raw_url:
        values["user_id"] = __ensure_user_id()
    url = raw_url.format(**config.CONFIG,**values)
    params = endpoint.get("params", {})
    http_method = endpoint.get("method", "get")
    body = endpoint.get("body", {})

    request.ensure_cookie()

    cache_f = None
    cache_tmp = __cache_file(method).with_suffix(".yaml.tmp")
    progress_file = __progress_file(method)
    results = []
    state = {}
    if __cache_mode(method) == "write":
        cache_tmp.parent.mkdir(parents=True, exist_ok=True)
        if not config.CONFIG.get("force") and progress_file.exists() and cache_tmp.exists():
            state = yaml.safe_load(progress_file.read_text(encoding="utf-8"))
            with cache_tmp.open("r+b") as f:  # drop anything written after the last saved batch
                f.truncate(state["size"])
            with cache_tmp.open("r", encoding="utf-8") as f:
                results.extend(__filter_items(yaml.safe_load(f) or [], endpoint))
            cache_f = cache_tmp.open("a", encoding="utf-8")
            print(f"[{method}] resuming: {len(results)} records kept from the interrupted run")
        else:
            progress_file.unlink(missing_ok=True)
            cache_f = cache_tmp.open("w", encoding="utf-8")
        print(f"[{method}] fetching from API, writing cache {__cache_file(method)}")

    def process(batch):
        if cache_f:
            for item in batch:
                cache_f.write(yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False))
        results.extend(__filter_items(batch, endpoint))

    def save_progress(**position):
        if cache_f:
            cache_f.flush()
            progress_file.write_text(yaml.safe_dump({**position, "size": cache_tmp.stat().st_size}), encoding="utf-8")

    try:
        if endpoint.get("pagination") == "offset":
            limit = endpoint.get("limit", 20)
            items_field = endpoint.get("items_field")
            offset = state.get("offset", 0)
            while True:
                if http_method == "post":
                    response = request.request(url, body={**body, "limit": limit, "offset": offset}, method=http_method)
                else:
                    response = request.request(url, params={**params, "limit": limit, "offset": offset})
                batch = response.get(items_field, []) if items_field and isinstance(response, dict) else response
                if not batch:
                    break
                process(batch)
                offset += len(batch)
                save_progress(offset=offset)
                if len(batch) < limit:
                    break
        elif endpoint.get("pagination") == "cursor":
            cursor_field = endpoint.get("cursor_field", "nextCursor")
            items_field = endpoint.get("items_field", "items")
            cursor = state.get("cursor")
            seen_cursors = set()
            while True:
                p = {**params, **({"cursor": cursor} if cursor else {})}
                response = request.request(url, params=p)
                batch = response.get(items_field, []) if isinstance(response, dict) else response
                if not batch:
                    break
                process(batch)
                cursor = response.get(cursor_field) if isinstance(response, dict) else None
                if not cursor:
                    break
                save_progress(cursor=cursor)
                if cursor in seen_cursors:
                    print(f"[{method}] cursor repeated, stopping to avoid an endless loop")
                    break
                seen_cursors.add(cursor)
        else:
            process(request.request(url, params=params))
    except BaseException:
        if cache_f and progress_file.exists():
            print(f"\n[{method}] interrupted, partial cache kept; run again to continue (--force starts over)")
        raise
    finally:
        if cache_f:
            cache_f.close()
    if cache_f:
        progress_file.unlink(missing_ok=True)
        cache_tmp.replace(__cache_file(method))
        print(f"[{method}] cache written: {__cache_file(method)}")

    return results


def do_request(method):
    if __cache_mode(method) != "read":
        return __fetch(method)

    print(f"[{method}] reading cache {__cache_file(method)}")
    with __cache_file(method).open("r", encoding="utf-8") as f:
        return __filter_items(yaml.safe_load(f), config.CONFIG[method])


def __collect(method):
    data_dir = Path(config.CONFIG["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    sort_key = config.CONFIG[method].get("sort_key")
    result = do_request(method)
    if sort_key:
        result = sorted(result, key=lambda x: x.get(sort_key), reverse=True)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--method", required=True)
    parser.add_argument("--cache", choices=["write", "read", "auto"], default="auto",
                        help="auto: read a fresh cache, otherwise fetch and write it (default); "
                             "write: always fetch; read: never fetch")
    parser.add_argument("--force", action="store_true",
                        help="do not continue an interrupted download, start it over")
    args = parser.parse_args()

    errors = config.validate_config(config.CONFIG)
    if errors:
        parser.error("invalid config.yaml:\n  " + "\n  ".join(errors))

    config.CONFIG["cache"] = args.cache
    config.CONFIG["force"] = args.force

    if not config.CONFIG.get("account_name"):
        parser.error("account_name is not set in config.yaml")

    if args.method == "all":
        for method in [k for k, v in config.CONFIG.items() if isinstance(v, dict) and "url" in v]:
            __collect(method)
    else:
        __collect(args.method)


if __name__ == "__main__":
    config.load_config()
    main()
