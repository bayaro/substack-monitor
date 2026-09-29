import argparse
import json
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--account")
    parser.add_argument("-m", "--method", required=True)
    args = parser.parse_args()

    account = args.account or load_config().get("account_name")
    if not account:
        parser.error("account required: pass -a or set account_name in config.yaml")

    result = do_request(account, args.method)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
