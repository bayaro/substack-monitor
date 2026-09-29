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
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

def __filter_columns(items, columns):
    if columns:
        return [{col: item.get(col) for col in columns} for item in items]
    return items


def __resolve_url(url, deps, data_dir):
    values = {}
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
    return url.format(**values)


def __collect(account, method, data_dir):
    result = sorted(do_request(account, method, data_dir), key=lambda x: x.get("id", 0), reverse=True)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")


def do_request(account_name, method, data_dir=None):
    config = load_config()
    endpoint = config[method]
    data_dir = data_dir or Path(config["data_dir"])

    raw_url = endpoint["url"]
    deps = endpoint.get("dependencies", {})
    if deps:
        url = __resolve_url(raw_url, deps, data_dir)
    else:
        url = f"https://{account_name}.substack.com/{raw_url}"

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
        results = []
        cursor = None
        while True:
            p = {**params, **({"cursor": cursor} if cursor else {})}
            response = __request(url, params=p)
            items = response.get("items", []) if isinstance(response, dict) else response
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

    account = args.account or load_config().get("account_name")
    if not account:
        parser.error("account required: pass -a or set account_name in config.yaml")

    config = load_config()
    data_dir = Path(config["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)

    if args.method == "all":
        for method in [k for k, v in config.items() if isinstance(v, dict) and "url" in v]:
            __collect(account, method, data_dir)
    else:
        __collect(account, args.method, data_dir)


if __name__ == "__main__":
    main()
