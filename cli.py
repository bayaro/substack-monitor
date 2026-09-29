import argparse
import json
from pathlib import Path
import yaml
import requests


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def __request(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=CONFIG.get("headers", {}),
        timeout=CONFIG.get("timeout", 30),
    )
    response.raise_for_status()
    return response.json()

def __extract(item, columns, prefix=""):
    record = {}
    for col in columns:
        if isinstance(col, str):
            key = f"{prefix}_{col}" if prefix else col
            record[key] = item.get(col) if isinstance(item, dict) else None
        elif isinstance(col, dict):
            for parent, subkeys in col.items():
                nested_prefix = f"{prefix}_{parent}" if prefix else parent
                record.update(__extract(item.get(parent) or {}, subkeys, nested_prefix))
    return record


def __flatten(item, prefix=""):
    record = {}
    for key, value in (item or {}).items():
        flat_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            record.update(__flatten(value, flat_key))
        else:
            record[flat_key] = value
    return record


def __filter_columns(items, columns):
    if not columns:
        return [__flatten(item) for item in items]
    return [__extract(item, columns) for item in items]


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


def __fetch(method):
    endpoint = CONFIG[method]
    columns = endpoint.get("columns")

    raw_url = endpoint["url"]
    if not raw_url.startswith("http"):
        raw_url = f"{CONFIG['base_url']}/{raw_url}"

    deps = endpoint.get("dependencies", {})
    url = raw_url.format(**CONFIG, **(__resolve_deps(deps) if deps else {}))
    params = endpoint.get("params", {})

    cache_f = None
    if CONFIG.get("cache"):
        cache_dir = Path(CONFIG["cache_dir"])
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_f = (cache_dir / f"{method}.yaml").open("w", encoding="utf-8")

    def process(batch):
        if cache_f:
            for item in batch:
                cache_f.write(yaml.safe_dump([item], allow_unicode=True, sort_keys=False, default_flow_style=False))
        return __filter_columns(batch, columns)

    try:
        if endpoint.get("pagination") == "offset":
            limit = endpoint.get("limit", 20)
            results = []
            offset = 0
            while True:
                batch = __request(url, params={**params, "limit": limit, "offset": offset})
                if not batch:
                    break
                results.extend(process(batch))
                offset += len(batch)
                if len(batch) < limit:
                    break
        elif endpoint.get("pagination") == "cursor":
            cursor_field = endpoint.get("cursor_field", "nextCursor")
            items_field = endpoint.get("items_field", "items")
            results = []
            cursor = None
            while True:
                p = {**params, **({"cursor": cursor} if cursor else {})}
                response = __request(url, params=p)
                batch = response.get(items_field, []) if isinstance(response, dict) else response
                if not batch:
                    break
                results.extend(process(batch))
                cursor = response.get(cursor_field) if isinstance(response, dict) else None
                if not cursor:
                    break
        else:
            results = process(__request(url, params=params))
    finally:
        if cache_f:
            cache_f.close()

    return results


def do_request(method, source_file=None):
    columns = CONFIG[method].get("columns")

    if source_file:
        with open(source_file, "r", encoding="utf-8") as f:
            return __filter_columns(yaml.safe_load(f), columns)

    return __fetch(method)


def __collect(method, source_file=None):
    data_dir = Path(CONFIG["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    sort_key = CONFIG[method].get("sort_key")
    result = do_request(method, source_file)
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
    parser.add_argument("-f", "--file")
    parser.add_argument("--cache", action="store_true")
    args = parser.parse_args()

    if args.account:
        CONFIG["account_name"] = args.account
    if args.cache:
        CONFIG["cache"] = True

    if not CONFIG.get("account_name"):
        parser.error("account required: pass -a or set account_name in config.yaml")

    if args.method == "all":
        for method in [k for k, v in CONFIG.items() if isinstance(v, dict) and "url" in v]:
            __collect(method)
    else:
        __collect(args.method, args.file)


if __name__ == "__main__":
    CONFIG = load_config()
    main()
