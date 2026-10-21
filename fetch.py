import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

import config
import record
import request


def __ensure_user_id():
    user_id_path = Path(config.CONFIG.user_id_file)
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
    return Path(config.CONFIG.cache_dir) / f"{method}.yaml"


def __progress_file(method):
    # where an interrupted download stands: next cursor/offset and the cache size that matches it
    return __cache_file(method).with_suffix(".yaml.progress")


def __tmp_file(method):
    return __cache_file(method).with_suffix(".yaml.tmp")


def __partial_age_minutes(method):
    # time since the last saved page of an interrupted download, None if there is no such download
    progress = __progress_file(method)
    if not (progress.exists() and __tmp_file(method).exists()):
        return None
    return (time.time() - progress.stat().st_mtime) / 60


def __resumable(method):
    age = __partial_age_minutes(method)
    return not config.CONFIG.force and age is not None and age < config.CONFIG.resume_max_age_minutes


def __cache_mode(method):
    mode = config.CONFIG.cache
    if mode != "read" and __resumable(method):
        return "write"  # an interrupted download is continued, whatever the cache age
    if mode != "auto":
        return mode
    cache_file = __cache_file(method)
    if cache_file.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        if age.total_seconds() < config.CONFIG.cache_auto_age_minutes * 60:
            return "read"
    return "write"


def fetch(method):
    endpoint = config.CONFIG.endpoints[method]

    raw_url = endpoint["url"]
    if not raw_url.startswith("http"):
        raw_url = f"{config.CONFIG.base_url}/{raw_url}"

    values = {}
    if "{user_id}" in raw_url:
        values["user_id"] = __ensure_user_id()
    url = raw_url.format(**vars(config.CONFIG), **values)
    params = endpoint.get("params", {})
    http_method = endpoint.get("method", "get")
    body = endpoint.get("body", {})

    request.ensure_cookie()

    cache_f = None
    cache_tmp = __tmp_file(method)
    progress_file = __progress_file(method)
    results = []
    state = {}
    if __cache_mode(method) == "write":
        cache_tmp.parent.mkdir(parents=True, exist_ok=True)
        if __resumable(method):
            state = yaml.safe_load(progress_file.read_text(encoding="utf-8"))
            with cache_tmp.open("r+b") as f:  # drop anything written after the last saved batch
                f.truncate(state["size"])
            with cache_tmp.open("r", encoding="utf-8") as f:
                results.extend(record.filter_items(yaml.safe_load(f) or [], endpoint))
            cache_f = cache_tmp.open("a", encoding="utf-8")
            print(f"[{method}] resuming: {len(results)} records kept from the interrupted run")
        else:
            age = __partial_age_minutes(method)
            if age is not None and not config.CONFIG.force:
                print(f"[{method}] interrupted download is {age:.0f} min old (limit {config.CONFIG.resume_max_age_minutes} min), starting over")
            progress_file.unlink(missing_ok=True)
            cache_f = cache_tmp.open("w", encoding="utf-8")
        print(f"[{method}] fetching from API, writing cache {__cache_file(method)}")

    def process(batch):
        if cache_f:
            for item in batch:
                cache_f.write(yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False))
        results.extend(record.filter_items(batch, endpoint))

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
        return fetch(method)

    print(f"[{method}] reading cache {__cache_file(method)}")
    with __cache_file(method).open("r", encoding="utf-8") as f:
        return record.filter_items(yaml.safe_load(f), config.CONFIG.endpoints[method])
