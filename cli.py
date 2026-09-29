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

def do_request(account_name, method):
    config = load_config()
    endpoint = config[method]

    url = f"https://{account_name}.substack.com/{endpoint['url']}"
    params = endpoint.get("params", {})
    columns = endpoint.get("columns")

    def filter(items):
        if columns:
            return [{col: item.get(col) for col in columns} for item in items]
        return items

    if endpoint.get("pagination") == "offset":
        limit = endpoint.get("limit", 20)
        results = []
        offset = 0
        while True:
            batch = __request(url, params={**params, "limit": limit, "offset": offset})
            if not batch:
                break
            results.extend(filter(batch))
            offset += len(batch)
            if len(batch) < limit:
                break
    else:
        results = filter(__request(url, params=params))

    return results

def collect(method):
    result = do_request(account, method)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")

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
            collect(method)
    else:
        collect(args.method)


if __name__ == "__main__":
    main()
