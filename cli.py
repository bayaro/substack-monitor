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

def __filter_columns(items, columns):
    if columns:
        return [{col: item.get(col) for col in columns} for item in items]
    return items


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


def __collect(method):
    data_dir = Path(CONFIG["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    result = sorted(do_request(method), key=lambda x: x.get("id", 0), reverse=True)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")


def do_request(method):
    endpoint = CONFIG[method]

    raw_url = endpoint["url"]
    if not raw_url.startswith("http"):
        raw_url = f"{CONFIG['base_url']}/{raw_url}"

    deps = endpoint.get("dependencies", {})
    url = raw_url.format(**CONFIG, **(__resolve_deps(deps) if deps else {}))

    params = endpoint.get("params", {})
    columns = endpoint.get("columns")

    if endpoint.get("pagination") == "offset":
        limit = endpoint.get("limit", 20)
        results = []
        offset = 0
        while True:
            batch = __request(url, params={**params, "limit": limit, "offset": offset})
            if not batch:
                break
            results.extend(__filter_columns(batch, columns))
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
            items = response.get(items_field, []) if isinstance(response, dict) else response
            if not items:
                break
            results.extend(__filter_columns(items, columns))
            cursor = response.get(cursor_field) if isinstance(response, dict) else None
            if not cursor:
                break
    else:
        results = __filter_columns(__request(url, params=params), columns)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--account")
    parser.add_argument("-m", "--method", required=True)
    args = parser.parse_args()

    if args.account:
        CONFIG["account_name"] = args.account

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
